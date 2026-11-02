"""The family portal: webtrees, fed from this repository and never edited by hand.

The tree stays where it is -- the GEDCOM at the root, kept with Ancestris -- and
the portal is a window onto it that is rebuilt from it: every import wipes the
tree in webtrees and loads it again. News, accounts and settings live outside
the genealogy tables in webtrees and survive that. Why webtrees and not Gramps
Web or a static site, and what is still to build, is issue #22.

Two commands:

    python -m tools.portal gedcoms DIR    # the files the portal imports
    python -m tools.portal local          # webtrees on this computer, to try it

`gedcoms` writes the whole tree without its BOM plus one file per branch in
`portal.branques` (config.yaml), cut by `tools.branca`. It is the step a deploy
job will run before uploading.

`local` installs webtrees 2.2.6 outside the repository (~/webtrees-prova by
default), with the JustLight theme and the magicsunday charts, one tree per
file and a test account per tree, and serves it on http://127.0.0.1:8080. Run
it again and it reloads every tree from the GEDCOM, which is what the real
portal will do after each merge; what was added through the web stays.

It needs PHP 8.3 or later (with pdo_sqlite, intl, mbstring and gd), git, and a
network connection the first time. On a Mac `brew install php`; on Debian or
Ubuntu `apt install php-cli php-sqlite3 php-intl php-mbstring php-gd php-xml
php-zip php-curl`; on Windows, from WSL.

Three things in webtrees 2.2.6 are worked around here, and each is a
contribution waiting to be made upstream (issue #22):

  * `tree-import` rejects a GEDCOM that starts with a BOM, which Ancestris
    always writes. Fixed on webtrees' main branch, not yet released.
  * `tree-setting REQUIRE_AUTHENTICATION 1` stores the setting in
    `gedcom_setting`, but 2.2.6 reads it from the column `gedcom.private`. A
    tree "made private" from the command line stays public.
  * `tree-import` looks the tree up with the permissions of the logged-in user,
    and on the command line there is none, so it cannot see private trees.
"""

from __future__ import annotations

import argparse
import io
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import config
from .branca import by_sosa, extract, summary, write
from .config import ROOT, ConfigError, tree_path
from .gedcom.lines import GedcomFile

WEBTREES = "2.2.6"
JUSTLIGHT = "2.4.0"
CHARTS = {
    "webtrees-fan-chart": "3.7.1",
    "webtrees-pedigree-chart": "2.7.4",
    "webtrees-descendants-chart": "2.6.4",
}
MIN_PHP = "8.3.0"  # the magicsunday charts ask for it
PHP_EXTENSIONS = ("pdo_sqlite", "intl", "mbstring", "gd")

# Every test account gets this. It is a local trial and says so on screen; the
# real portal's accounts are made by whoever runs it.
TEST_PASSWORD = "provaprova"


@dataclass(frozen=True)
class Tree:
    """One tree in the portal: the whole one, or a branch."""

    name: str  # webtrees' short name, also the account that can see it
    title: str
    root: str  # xref of the person the tree opens on
    language: str
    account: str
    branch: bool


def trees(cfg: dict, ged: GedcomFile) -> list[Tree]:
    """The trees `portal:` in config.yaml asks for, the whole one first."""
    portal = cfg.get("portal") or {}
    language = portal.get("llengua") or "ca"
    root = (
        portal.get("arrel")
        or (cfg.get("estat") or {}).get("arrel")
        or _sosa_or_none(ged, 1)
        or ged.of_type("INDI")[0].xref
    )
    out = [Tree(
        name=portal.get("nom") or "arbre",
        title=portal.get("titol") or "Arbre familiar",
        root=root.strip("@"),
        language=language,
        account="familia",
        branch=False,
    )]
    for name, spec in (portal.get("branques") or {}).items():
        spec = spec or {}
        if spec.get("sosa"):
            branch_root = by_sosa(ged, int(spec["sosa"]))
        elif spec.get("xref"):
            branch_root = str(spec["xref"]).strip("@")
        else:
            raise ConfigError(f"portal.branques.{name}: cal `sosa:` o `xref:`.")
        out.append(Tree(
            name=name,
            title=spec.get("titol") or name,
            root=branch_root,
            language=spec.get("llengua") or language,
            account=spec.get("compte") or name,
            branch=True,
        ))
    names = [t.name for t in out]
    if len(set(names)) != len(names):
        raise ConfigError("portal: dos arbres amb el mateix nom.")
    return out


def _sosa_or_none(ged: GedcomFile, sosa: int) -> str | None:
    try:
        return by_sosa(ged, sosa)
    except ConfigError:
        return None


def gedcoms(out_dir: Path, ged: GedcomFile, plan: list[Tree]) -> dict[str, Path]:
    """Write one importable GEDCOM per tree. Returns {tree name: file}."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    for tree in plan:
        path = out_dir / f"{tree.name}.ged"
        if tree.branch:
            branch = extract(ged, tree.root)
            write(ged, branch, path)
            print(f"{path.name}: {summary(ged, branch)}")
        else:
            # The whole file, as it is, minus the BOM.
            text = ged.render()
            path.write_text(text.lstrip("﻿"), encoding="utf-8", newline="")
            print(f"{path.name}: l'arbre sencer, {len(ged.of_type('INDI'))} persones")
        files[tree.name] = path
    return files


# -- the local trial ------------------------------------------------------


class Webtrees:
    """A webtrees installation driven through its command line and its database."""

    def __init__(self, base: Path, port: int):
        self.base = base
        self.dir = base / "webtrees"
        self.db = self.dir / "data" / "webtrees.sqlite"
        self.url = f"http://127.0.0.1:{port}"
        self.port = port
        self.server: subprocess.Popen | None = None

    def cli(self, *args: str) -> str:
        done = subprocess.run(
            ["php", "index.php", *args], cwd=self.dir, capture_output=True, text=True
        )
        if done.returncode != 0:
            raise SystemExit(f"webtrees {' '.join(args)}:\n{done.stdout}{done.stderr}")
        return done.stdout

    def sql(self, query: str, params: tuple = ()) -> list[tuple]:
        with sqlite3.connect(self.db) as db:
            return db.execute(query, params).fetchall()

    # installation

    def install(self) -> None:
        downloads = self.base / "baixades"
        downloads.mkdir(parents=True, exist_ok=True)
        if not (self.dir / "index.php").exists():
            print(f"Baixant webtrees {WEBTREES}…")
            _unzip(_download(
                f"https://github.com/fisharebest/webtrees/releases/download/{WEBTREES}/webtrees-{WEBTREES}.zip",
                downloads,
            ), self.base)
        modules = self.dir / "modules_v4"
        for name, version in CHARTS.items():
            if not (modules / name / "module.php").exists():
                print(f"Baixant {name} {version}…")
                _unzip(_download(
                    f"https://github.com/magicsunday/{name}/releases/download/{version}/{name}.zip",
                    downloads,
                ), modules / name)
        theme = modules / "justlight"  # the folder name is the module name: _justlight_
        if not (theme / "module.php").exists():
            print(f"Baixant el tema JustLight {JUSTLIGHT}…")
            subprocess.run(
                ["git", "-c", "advice.detachedHead=false", "clone", "-q", "--depth", "1",
                 "--branch", JUSTLIGHT,
                 "https://github.com/justcarmen/webtrees-theme-justlight.git", str(theme)],
                check=True,
            )
            shutil.rmtree(theme / ".git", ignore_errors=True)

        # The GEDCOM's paths are relative to the repository ("Fonts/…"), and
        # webtrees looks for them inside the tree's media folder.
        media = self.dir / "data" / "media"
        media.mkdir(parents=True, exist_ok=True)
        link = media / "Fonts"
        if (ROOT / "Fonts").is_dir() and not link.exists():
            link.symlink_to(ROOT / "Fonts", target_is_directory=True)

    def serve(self) -> None:
        log = open(self.base / "servidor.log", "w")
        self.server = subprocess.Popen(
            ["php", "-S", f"127.0.0.1:{self.port}", "-t", str(self.dir)],
            stdout=log, stderr=subprocess.STDOUT,
        )
        for _ in range(50):
            if self.get("/") is not None:
                return
            time.sleep(0.2)
        raise SystemExit(f"El servidor no respon a {self.url}; vegeu {log.name}.")

    def get(self, path: str) -> int | None:
        try:
            with urllib.request.urlopen(self.url + path, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return None

    def create_database(self) -> None:
        if self.db.exists():
            return
        print("Creant la base de dades…")
        self.db.touch()  # config-ini connects to it, and SQLite wants it to exist
        self.cli("config-ini", "--dbtype=sqlite", "--dbname=webtrees", f"--base-url={self.url}")
        self.get("/index.php")  # the first request creates the tables
        # What the web setup wizard does and the command line does not: the
        # "default" tree and user where webtrees keeps the initial values.
        # Without them the first tree page fails on a foreign key.
        with sqlite3.connect(self.db) as db:
            db.execute("INSERT OR IGNORE INTO gedcom (gedcom_id, gedcom_name, sort_order, imported, private)"
                       " VALUES (-1, 'DEFAULT_TREE', 0, 0, 0)")
            db.execute("INSERT OR IGNORE INTO user (user_id, user_name, real_name, email, password)"
                       " VALUES (-1, 'DEFAULT_USER', 'DEFAULT_USER', 'DEFAULT_USER', 'DEFAULT_USER')")
            for tag, resn in {"SSN": "confidential", "SOUR": "privacy", "REPO": "privacy",
                              "SUBM": "confidential", "SUBN": "confidential"}.items():
                db.execute("INSERT OR IGNORE INTO default_resn (gedcom_id, tag_type, resn)"
                           " VALUES (-1, ?, ?)", (tag, resn))
        self.cli("user", "--create", "--real-name=Administrador",
                 "--email=admin@example.invalid", f"--password={TEST_PASSWORD}", "admin")
        self.cli("user-setting", "admin", "canadmin", "1")
        self.cli("site-setting", "THEME_DIR", "_justlight_")

    def ensure(self, plan: list[Tree]) -> None:
        """Every tree and test account the plan asks for. New branches get added."""
        existing = {row[0] for row in self.sql("SELECT gedcom_name FROM gedcom")}
        users = {row[0] for row in self.sql("SELECT user_name FROM user")}
        for tree in plan:
            if tree.name not in existing:
                print(f"Creant l'arbre {tree.name}…")
                self.cli("tree", "--create", f"--title={tree.title}", tree.name)
                self.cli("user-tree-setting", "admin", tree.name, "canedit", "admin")
            self.cli("tree-setting", tree.name, "PEDIGREE_ROOT_ID", tree.root)
            if tree.account not in users:
                self.cli("user", "--create", f"--real-name={tree.title}",
                         f"--email={tree.account}@example.invalid",
                         f"--password={TEST_PASSWORD}", tree.account)
                self.cli("user-setting", tree.account, "language", tree.language)
                # Access to this tree and to no other.
                self.cli("user-tree-setting", tree.account, tree.name, "canedit", "access")
                users.add(tree.account)
        self.cli("user-setting", "admin", "language", plan[0].language)
        self.cli("site-setting", "LANGUAGE", plan[0].language)
        self.cli("site-setting", "DEFAULT_GEDCOM", plan[0].name)

    def private(self, on: bool) -> None:
        self.sql("UPDATE gedcom SET private = ? WHERE gedcom_id > 0", (int(on),))

    def load(self, files: dict[str, Path]) -> None:
        print("Important els arbres…")
        # Made public only while importing: see the module docstring.
        self.private(False)
        try:
            for name, path in files.items():
                self.cli("tree-import", "--quiet", name, str(path))
        finally:
            self.private(True)


def _download(url: str, folder: Path) -> Path:
    path = folder / url.rsplit("/", 1)[1]
    if not path.exists() or path.stat().st_size == 0:
        with urllib.request.urlopen(url, timeout=120) as r:
            path.write_bytes(r.read())
    return path


def _unzip(path: Path, into: Path) -> None:
    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
        z.extractall(into)


def _check_requirements() -> None:
    for tool in ("php", "git"):
        if shutil.which(tool) is None:
            raise ConfigError(f"Falta {tool}: vegeu `python -m tools.portal --help`.")
    version = subprocess.run(["php", "-r", "echo PHP_VERSION;"], capture_output=True, text=True).stdout
    ok = subprocess.run(["php", "-r", f"exit(version_compare(PHP_VERSION, '{MIN_PHP}', '>=') ? 0 : 1);"])
    if ok.returncode != 0:
        raise ConfigError(f"Cal PHP {MIN_PHP} o més nou; aquest és el {version}.")
    loaded = set(subprocess.run(["php", "-m"], capture_output=True, text=True).stdout.split())
    missing = [e for e in PHP_EXTENSIONS if e not in loaded]
    if missing:
        raise ConfigError(f"Falten extensions de PHP: {', '.join(missing)}.")


def local(base: Path, port: int) -> int:
    _check_requirements()
    ged = GedcomFile(tree_path())
    plan = trees(config.load(), ged)
    wt = Webtrees(base, port)
    wt.install()
    wt.serve()
    try:
        wt.create_database()
        wt.ensure(plan)
        wt.load(gedcoms(base / "gedcom", ged, plan))
        print(f"\nwebtrees és a {wt.url}  (Ctrl+C per aturar-lo)\n")
        print(f"  {'admin':<12} {TEST_PASSWORD}   ho veu tot i ho configura tot")
        for tree in plan:
            print(f"  {tree.account:<12} {TEST_PASSWORD}   només «{tree.title}» ({tree.language})")
        print()
        wt.server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        wt.server.terminate()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=__doc__.split("\n\n", 1)[1],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="ordre", required=True)
    g = sub.add_parser("gedcoms", help="escriu els GEDCOM que el portal importa")
    g.add_argument("dir", type=Path)
    loc = sub.add_parser("local", help="munta webtrees en aquest ordinador per provar-lo")
    loc.add_argument("--dir", type=Path, default=Path.home() / "webtrees-prova")
    loc.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)

    if args.ordre == "gedcoms":
        ged = GedcomFile(tree_path())
        gedcoms(args.dir, ged, trees(config.load(), ged))
        return 0
    return local(args.dir.expanduser().resolve(), args.port)


if __name__ == "__main__":
    sys.exit(main())

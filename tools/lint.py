"""Checks that fail. Nothing here ever rewrites prose.

A tool writing into a file a human also edits goes wrong sooner or later --
the writer's own summary line pasted over the document, a `>` typo, a run cut
short mid-write. So the numbers get *generated* into `reports/estat.md` (see
`tools.estat`) and any hand-written prose that repeats one gets *checked*
against it -- named file, named line, both values printed, fixed by hand.

That also protects the numbers that must not change. A sentence can say what a
document contributed on a given date -- "aquest bateig va confirmar la filiació
del 12 al 16" -- and stay true as history even after the live count moves on. A
rewriter cannot tell those from a live claim; a check that only looks at known
table rows can.

    python -m tools.lint                # every check
    python -m tools.lint --xifres       # stale numbers in hand-written prose
    python -m tools.lint --rutes        # Fonts/ paths cited by the GEDCOM
    python -m tools.lint --xrefs        # an xref names the person written beside it
    python -m tools.lint --cr-id        # nothing carries a plugin cr_id
    python -m tools.lint --frontmatter  # our own vocabulary, and the YAML traps
    python -m tools.lint --privacitat   # binaries tracked only while private
    python -m tools.lint --duplicacio   # writes reports/duplicacio.md
    python -m tools.lint --informes     # reports/frontier.md and worklist.md are current
    python -m tools.lint --generic      # no hi ha cap dada de família dins de tools/
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from . import frontmatter as fm
from . import report as report_writer
from .config import tree_path
from .estat import Estat, ROOT, _FONTS_PATH
from .normalize import fold

FONTS = ROOT / "Fonts"
REPORTS = ROOT / "reports"

# Extensions that are binary for our purposes: the licence story turns on which
# of these are tracked, so the list is explicit rather than "not .md".
BINARY = {".jpg", ".jpeg", ".png", ".svg", ".pdf", ".ogg", ".xlsx", ".docx", ".eml"}


class Report:
    """Collected failures. Printing is the whole interface."""

    def __init__(self) -> None:
        self.problems: list[str] = []
        self.notes: list[str] = []

    def fail(self, where: str, message: str) -> None:
        self.problems.append(f"{where}\t{message}")

    def note(self, message: str) -> None:
        self.notes.append(message)

    def show(self, label: str) -> int:
        for line in self.notes:
            print(f"  {line}")
        for line in self.problems:
            print(line)
        if self.problems:
            print(f"{len(self.problems)} {label}")
            return 1
        print(f"0 {label}")
        return 0


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").split("\n")


def _int(text: str) -> int | None:
    m = re.search(r"\d+", text.replace(".", ""))
    return int(m.group()) if m else None


# Catalan ordinals as they are written in a README's generation table.
_ORDINALS = (
    "primera", "segona", "tercera", "quarta", "cinquena", "sisena", "setena",
    "vuitena", "novena", "desena", "onzena", "dotzena", "tretzena", "catorzena",
    "quinzena", "setzena", "dissetena", "divuitena", "dinovena", "vintena",
)


def _generation_row(label: str) -> int | None:
    """`Sisena generació` -> 6, anything else -> None."""
    words = label.strip().lower().split()
    if len(words) != 2 or words[1] != "generació":
        return None
    return _ORDINALS.index(words[0]) + 1 if words[0] in _ORDINALS else None


# -- xifres ---------------------------------------------------------------


def check_xifres(estat: Estat, report: Report, root: Path | None = None) -> None:
    """Hand-written counts in README.md against the computed ones.

    Only `| Label | value |` rows whose label matches one of `tools.estat`'s
    own table rows are inspected -- copy the label, and the check follows.
    Anything else in the prose is left alone on purpose: a check that rewrites
    or second-guesses prose it does not understand is worse than no check.
    """
    rows = {
        "Persones a l'arbre": estat.people,
        "Famílies": estat.families,
        "Amb identificador de FamilySearch": estat.with_fsftid,
        "Sense pares (front de recerca)": estat.without_parents,
    }
    every, markdown, lectura = estat.fonts_files()
    routes, route_lines, _ = estat.gedcom_paths()
    root = root or ROOT
    readme = root / "README.md"
    if not readme.exists():
        return
    for n, line in enumerate(_lines(readme), 1):
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        if label in rows:
            said = _int(value)
            if said is not None and said != rows[label]:
                report.fail(f"README.md:{n}", f"{label}: diu {said}, són {rows[label]}")

        # `| Sisena generació | **30 de 32** |`: how full a generation is. The
        # total is not a number anybody should be typing -- generation N has
        # 2**(N-1) slots -- so it is computed and compared too.
        want = _generation_row(label)
        if want is not None:
            filled, _ = estat.generation(want)
            m = re.search(r"(\d+)\s+de\s+(\d+)", value)
            total = 2 ** (want - 1)
            if m and (int(m.group(1)), int(m.group(2))) != (filled, total):
                report.fail(
                    f"README.md:{n}",
                    f"{label}: diu «{m.group()}», són «{filled} de {total}»",
                )

    # The inventory sentence, which used to disagree with itself as well as with
    # the disk: "68 fitxers, 30 dels quals .md" against "107 fitxers, 60".
    sentence = re.compile(r"\*?\*?(\d+) fitxers, (\d+) dels quals")
    for relative in ("README.md", "Fonts/00 LLEGIU-ME.md"):
        path = root / relative
        if not path.exists():
            continue
        for n, line in enumerate(_lines(path), 1):
            m = sentence.search(line)
            if m and (int(m.group(1)), int(m.group(2))) != (every, markdown):
                report.fail(
                    f"{relative}:{n}",
                    f"diu «{m.group(1)} fitxers, {m.group(2)} dels quals .md», "
                    f"són {every} / {markdown}",
                )

    # The GEDCOM path counts, which were stated in two files with three
    # different numbers.
    for relative in ("README.md", "Fonts/00 LLEGIU-ME.md"):
        path = root / relative
        if not path.exists():
            continue
        for n, line in enumerate(_lines(path), 1):
            if "Fonts/" not in line and "rutes" not in line:
                continue
            m = re.search(r"\*\*(\d+) línies\*\*", line)
            if m and int(m.group(1)) != route_lines:
                report.fail(
                    f"{relative}:{n}",
                    f"rutes al GEDCOM: diu {m.group(1)} línies, són {route_lines}",
                )
            m = re.search(r"(\d+) bones", line)
            if m and int(m.group(1)) != routes:
                report.fail(
                    f"{relative}:{n}",
                    f"la comprovació de rutes: diu «{m.group(1)} bones», són {routes}",
                )


# -- rutes ----------------------------------------------------------------


def check_rutes(estat: Estat, report: Report) -> None:
    """Every Fonts/ path cited by the GEDCOM exists.

    A copy-pasteable heredoc in a README drifts the moment nobody re-runs it by
    hand; a check does not. `Fonts/00 LLEGIU-ME.md` carries the same heredoc for
    someone who wants it without installing the tools -- keep both in sync if
    the regex ever changes.
    """
    routes, lines, broken = estat.gedcom_paths()
    report.note(f"{routes} rutes en {lines} línies, {len(broken)} trencades")
    tree_name = tree_path().name
    for route in broken:
        report.fail(tree_name, f"ruta trencada: {route}")

    # Folder-only references are not covered by the file regex, which ends at an
    # extension -- some lines cite a directory instead. Where a folder name
    # contains spaces there is no way to tell where it stops, so instead of
    # guessing, try every prefix ending in `/` and accept the longest that is a
    # real directory. Only a reference where none matches is a failure.
    folders = 0
    for raw in estat.tree.ged.raw:
        for start in (m.start() for m in re.finditer(r"Fonts/", raw)):
            rest = raw[start:]
            if _FONTS_PATH.match(rest):
                continue  # a file reference, already counted above
            longest = None
            for m in re.finditer(r"/", rest):
                candidate = rest[: m.end()]
                if (ROOT / candidate).is_dir():
                    longest = candidate
            if longest:
                folders += 1
            else:
                report.fail(tree_name, f"referència que no resol: {rest[:60]!r}")
    report.note(f"{folders} referències a una carpeta, totes existents")


# -- xrefs ----------------------------------------------------------------

# `@I00098@ Pere Tarrats i Sabadí` -- the xref and the name written beside it.
_XREF_NAMED = re.compile(
    r"@(I\d{5})@\s*[*_`]{0,2}"
    r"((?:[A-ZÀ-Ú][\wÀ-ɏ'’]*(?:\s+(?:i|de|del|la)\s+)?[ ]?){1,4})"
)

# Words that follow an xref without being part of a name.
_NOT_A_NAME = {"sosa", "els", "que", "amb", "del", "les", "una", "seu", "seua"}


def check_xrefs(estat: Estat, report: Report) -> None:
    """Does the name written next to an xref belong to that xref?

    `--frontmatter` already checks that an xref *exists*. This checks something
    else and harder: that it is the *right* person. A Sosa number and an xref
    look similar enough on the page that one can leak into the other's spot,
    and nothing else catches it -- the file still parses, the xref still
    resolves, it just names somebody else.

    Spelling drift is tolerated with the same fuzzy match the document
    heuristic uses, because sources disagree on spellings that mean one
    person: transcription variants, a Castilianised given name, a lost accent.
    And a lone given name is never flagged, since a documented alias -- an
    index that calls someone by a name nobody else uses for them -- is a real
    and legitimate case.
    """
    checked = 0
    for path in sorted(FONTS.rglob("*.md")):
        if ".obsidian" in path.parts:
            continue
        relative = str(path.relative_to(ROOT))
        for n, line in enumerate(_lines(path), 1):
            for match in _XREF_NAMED.finditer(line):
                xref, written = match.group(1), match.group(2).strip()
                person = estat.tree.people.get(xref)
                if person is None:
                    report.fail(f"{relative}:{n}", f"@{xref}@ no existeix al GEDCOM")
                    continue
                words = [
                    w
                    for w in fold(written).split()
                    if len(w) > 2 and w not in _NOT_A_NAME
                ]
                if len(words) < 2:
                    continue  # a lone given name may be a documented alias
                checked += 1
                actual = fold(f"{person.given} {person.surname}").split()
                if not any(
                    any(
                        SequenceMatcher(None, w, other).ratio() >= 0.85
                        for other in actual
                    )
                    for w in words
                ):
                    report.fail(
                        f"{relative}:{n}",
                        f"diu «@{xref}@ {written}» però la @{xref}@ és "
                        f"{person.given} {person.surname}",
                    )
    report.note(f"{checked} mencions amb nom comprovades")


# -- cr_id ----------------------------------------------------------------


def check_cr_id(report: Report) -> None:
    """No tracked note may carry a `cr_id`.

    It is the key that arms the obsidian-charted-roots writers: the plugin's
    modify and delete handlers are both gated on the note having one. Without a
    `cr_id` neither ever fires, so the plugin can stay installed and our own
    notes stay invisible to it -- our vocabulary needs nothing from it. See
    `tools.frontmatter` and `tools.obsidian` for the rest of that arrangement.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "*.md"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    for relative in filter(None, tracked):
        path = ROOT / relative
        if not path.exists():
            continue
        for n, line in enumerate(_lines(path), 1):
            if re.match(r"\s*cr_id\s*:", line):
                report.fail(f"{relative}:{n}", "cr_id en un fitxer seguit")


# -- privacitat -----------------------------------------------------------


def check_privacitat(report: Report) -> None:
    """Binaries under Fonts/ are only allowed while the repository is private.

    FamilySearch forbids republication of what it returns, and diocesan
    archives typically permit personal-use copies but charge for
    republication -- `Fonts/00 LLEGIU-ME.md` says which apply to what you have.
    Until assets are tracked at all, the `.gitignore` is what guarantees none
    of it leaks; once a binary is tracked, repository privacy is the guarantee
    instead, so it has to be asserted here, not assumed.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "Fonts/"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    binaries = [
        f for f in filter(None, tracked) if Path(f).suffix.lower() in BINARY
    ]
    report.note(f"{len(binaries)} binaris seguits sota Fonts/")
    if not binaries:
        return

    try:
        seen = subprocess.run(
            ["gh", "repo", "view", "--json", "isPrivate"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=30,
        )
        private = json.loads(seen.stdout).get("isPrivate")
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        report.fail("gh repo view", f"no s'ha pogut comprovar la privacitat: {exc}")
        return

    if private is not True:
        report.fail(
            "el repositori",
            f"és públic i hi ha {len(binaries)} binaris seguits sota Fonts/",
        )


# -- duplicacio -----------------------------------------------------------

_WORD = re.compile(r"\w+", re.UNICODE)
SHINGLE = 12


def _words(text: str) -> list[str]:
    """Prose words only: the frontmatter block and markdown table rows are dropped.

    Both exclusions are for the same reason -- structured data agreeing with
    itself is not prose copied from one file to another, and left in it
    outranks every real finding. Several siblings' index cards can carry an
    identical `| Vincle | Nom | Lloc |` table because they genuinely share the
    same parents and grandparents; every note from one archive can carry the
    same `condicions:` and the same `arxiu:`, which is the point of having
    those keys.

    Blockquotes stay: a transcription that lives both in its `.md` and in a
    GEDCOM `NOTE` is exactly the duplication we want to see.
    """
    lines = text.split("\n")
    if lines and lines[0] == "---":
        closing = next((i for i, line in enumerate(lines[1:], 1) if line == "---"), None)
        if closing is not None:
            lines = lines[closing + 1 :]
    prose = [line for line in lines if not line.lstrip().startswith("|")]
    return _WORD.findall("\n".join(prose))


def _shingles(words: list[str]) -> dict[tuple[str, ...], int]:
    """Every SHINGLE-word run, lowercased, mapped to where it starts."""
    lowered = [w.lower() for w in words]
    out: dict[tuple[str, ...], int] = {}
    for i in range(len(lowered) - SHINGLE + 1):
        out.setdefault(tuple(lowered[i : i + SHINGLE]), i)
    return out


def _longest_run(positions: list[int]) -> tuple[int, int]:
    """(words in the longest contiguous passage, where it starts).

    Consecutive shingle positions mean overlapping text, so a run of k of them
    is k + SHINGLE - 1 contiguous words. This is what separates real copying
    from a shared template: two index transcriptions of the same class share
    dozens of *short* runs -- the metadata table's own headings -- while a
    pasted argument is one *long* one. Ranking by count surfaces the
    boilerplate; ranking by length surfaces the copy.
    """
    if not positions:
        return 0, 0
    ordered = sorted(positions)
    best_length, best_start = 1, ordered[0]
    run, start = 1, ordered[0]
    for previous, current in zip(ordered, ordered[1:]):
        if current == previous + 1:
            run += 1
        else:
            run, start = 1, current
        if run > best_length:
            best_length, best_start = run, start
    return best_length + SHINGLE - 1, best_start


def check_duplicacio(estat: Estat, report: Report) -> None:
    """Verbatim runs shared between files, written to reports/duplicacio.md.

    Nothing is fixed here. This exists so that "a transcription does not
    argue, and a reasoning lives in one place" becomes a number that goes down
    instead of a rule nobody can check they are honouring.
    """
    sources: dict[str, str] = {}
    for path in sorted(FONTS.rglob("*.md")):
        if ".obsidian" in path.parts:
            continue
        sources[str(path.relative_to(ROOT))] = path.read_text(encoding="utf-8")
    for extra in sorted(REPORTS.glob("*.md")):
        sources[str(extra.relative_to(ROOT))] = extra.read_text(encoding="utf-8")

    # The GEDCOM's NOTE prose is a home for the same text, and the one nobody
    # counts by hand: Catalan prose across NOTE/CONT/CONC lines.
    tree_name = tree_path().name
    notes = [
        raw.split(" ", 2)[2]
        for raw in estat.tree.ged.raw
        if re.match(r"\d (?:NOTE|CONT|CONC) ", raw)
    ]
    sources[f"{tree_name} (NOTE)"] = "\n".join(notes)

    words = {name: _words(text) for name, text in sources.items()}
    shingles = {name: _shingles(w) for name, w in words.items()}

    index: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for name, table in shingles.items():
        for shingle in table:
            index[shingle].append(name)

    # For each pair, where the shared shingles start in the first file.
    shared: dict[tuple[str, str], list[int]] = defaultdict(list)
    for shingle, names in index.items():
        if len(names) < 2:
            continue
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                first, second = (a, b) if a < b else (b, a)
                shared[(first, second)].append(shingles[first][shingle])

    ranked = []
    for (a, b), positions in shared.items():
        length, start = _longest_run(positions)
        excerpt = " ".join(words[a][start : start + min(length, 18)])
        ranked.append((length, len(positions), a, b, excerpt))
    ranked.sort(key=lambda row: -row[0])

    out = [
        "# Duplicació de prosa",
        "",
        "**Generat per `python -m tools.lint --duplicacio`.**",
        "",
        "No és una llista d'errors: **la redundància d'un fet estable no costa res.**",
        "El que costa és un fet que *canvia* i viu a diversos llocs, perquè corregir-lo",
        "vol dir trobar-los tots i corregir-los tots.",
        "",
        "Ordenat per **passatge idèntic més llarg**, no per nombre de coincidències.",
        "Això és a posta: dues fitxes de l'índex de la mateixa classe comparteixen",
        "moltes coincidències *curtes* —les capçaleres de la seua pròpia taula— i això",
        "està bé. Un raonament copiat és **una de llarga**. Ordenar per nombre treu",
        "la plantilla a la superfície i amaga la còpia.",
        "",
        f"{len(ranked)} parelles de fitxers comparteixen almenys {SHINGLE} paraules.",
        "",
        "| Paraules seguides | Coincidències | Fitxers | Comença per |",
        "| --- | --- | --- | --- |",
    ]
    for length, count, a, b, excerpt in ranked[:50]:
        out.append(f"| **{length}** | {count} | `{a}`<br>`{b}` | …{excerpt}… |")
    if len(ranked) > 50:
        out.append(f"| … | | i {len(ranked) - 50} parelles més | |")

    path = report_writer.write(REPORTS / "duplicacio.md", "\n".join(out) + "\n")
    longest = ranked[0][0] if ranked else 0
    report.note(
        f"{len(ranked)} parelles amb text compartit, la més llarga de {longest} paraules"
    )
    report.note(f"wrote {path.relative_to(ROOT)}")


# -- informes ---------------------------------------------------------------


def check_informes(estat: Estat, report: Report, reports_dir: Path = REPORTS) -> None:
    """`reports/frontier.md` and `reports/worklist.md` against what they'd render today.

    Nothing regenerates these two on its own, so nothing keeps them honest
    unless something checks. This is the same fix `tools.estat` already applies
    to the numbers in prose, for the two reports `tools.frontier` and
    `tools.worklist` write.

    Imported here, not at module level, because `tools.frontier` pulls in
    `tools.fs.fetch` and therefore `requests` -- `tools.lint` should keep
    running with nothing but the standard library and PyYAML.
    """
    from . import frontier, worklist

    canon = estat.tree
    live = None
    pedigree_path = frontier.PEDIGREE
    if pedigree_path.exists():
        from .fs.fetch import LiveTree

        live = LiveTree.from_json(json.loads(pedigree_path.read_text(encoding="utf-8")))
    snapshot = None if live else frontier.snapshot_load(frontier.SNAPSHOT)
    if not live and not snapshot:
        report.note(
            "cap pedigrí ni instantània: --informes no pot comprovar la part de "
            "FamilySearch, només que la resta de reports/frontier.md i "
            "reports/worklist.md concorden amb el GEDCOM"
        )

    entries = frontier.build(canon, live, snapshot)

    def render_frontier(scratch: Path) -> None:
        frontier.write_report(entries, canon, live, snapshot, scratch)

    def render_worklist(scratch: Path) -> None:
        worklist.write_report(entries, scratch, live, snapshot)

    for name, render in (("frontier.md", render_frontier), ("worklist.md", render_worklist)):
        path = reports_dir / name
        if not path.exists():
            report.fail(f"reports/{name}", "no existeix: genera'l amb l'eina corresponent")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / name
            render(scratch)
            fresh = scratch.read_text(encoding="utf-8")
        committed = path.read_text(encoding="utf-8")
        if fresh == committed:
            continue
        committed_lines = committed.split("\n")
        fresh_lines = fresh.split("\n")
        for n, (old, new) in enumerate(zip(committed_lines, fresh_lines), start=1):
            if old != new:
                report.fail(
                    f"reports/{name}:{n}",
                    f"diu {old.strip()!r}, hauria de dir {new.strip()!r} — "
                    f"torna'l a generar amb python -m tools.{Path(name).stem}",
                )
                break
        else:
            report.fail(
                f"reports/{name}",
                f"té {len(committed_lines)} línies i n'hauria de tenir "
                f"{len(fresh_lines)} — torna'l a generar amb "
                f"python -m tools.{Path(name).stem}",
            )


# -- generic ---------------------------------------------------------------


# Where the family data is allowed to be: `config.yaml`, and nowhere else.
# Everything under `tools/` is the package, and the package is shared with
# every other family that starts from this template.
#
# This check exists because the sharing failed once already. The tools were
# copied into a family repository instead of installed, and by 26-08-2026 the
# two copies differed in 39 of 44 files -- because the copy that had the real
# tree grew real names inside the code, and could no longer be given back.
#
# It looks for the shapes that data takes when it leaks: a GEDCOM xref in
# quotes, a FamilySearch PID, an ancestor's name. It cannot catch prose in a
# comment, and it is not meant to: what it catches is a value the code will
# *act* on.
_XREF_LITERAL = re.compile(r"[IFS]\d{4,5}")
_FS_PID = re.compile(r"[A-Z0-9]{4}-[A-Z0-9]{3}")

# Files that legitimately carry the shapes above.
_GENERIC_EXEMPT = {
    "config.py",       # it is the one that reads config.yaml
    "tests",           # fixtures name the example tree on purpose
}


def check_generic(report: Report) -> None:
    """No xref, PID or place decides anything inside `tools/`.

    The rule, from `tools/config.py`'s own docstring: if you are about to write
    a name, an xref or a town into the code, it belongs in `config.yaml`.

    Only *values the code acts on* are inspected, and that is why this reads
    the syntax tree instead of the text. A docstring saying «e.g. "I00176"» is
    documentation and stays; the same string in a `set` is a decision, and the
    next family to use this package inherits it silently.
    """
    tools = Path(__file__).resolve().parent
    checked = 0
    for path in sorted(tools.rglob("*.py")):
        relative = path.relative_to(tools)
        if relative.parts[0] in _GENERIC_EXEMPT or relative.name in _GENERIC_EXEMPT:
            continue
        checked += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError) as exc:
            report.fail(f"tools/{relative}", f"no s'ha pogut llegir: {exc}")
            continue
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings:
                continue
            for pattern, what in ((_XREF_LITERAL, "un xref"),
                                  (_FS_PID, "un PID de FamilySearch")):
                if pattern.fullmatch(node.value):
                    report.fail(
                        f"tools/{relative}:{node.lineno}",
                        f"{what} escrit al codi ({node.value!r}): va a config.yaml",
                    )
    report.note(f"{checked} fitxers de tools/ mirats")


# -- cli ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xifres", action="store_true")
    parser.add_argument("--rutes", action="store_true")
    parser.add_argument("--xrefs", action="store_true")
    parser.add_argument("--cr-id", action="store_true")
    parser.add_argument("--frontmatter", action="store_true")
    parser.add_argument("--privacitat", action="store_true")
    parser.add_argument("--duplicacio", action="store_true")
    parser.add_argument("--informes", action="store_true")
    parser.add_argument("--generic", action="store_true")
    args = parser.parse_args(argv)

    chosen = any(
        (args.xifres, args.rutes, args.xrefs, args.cr_id, args.frontmatter,
         args.privacitat, args.duplicacio, args.informes, args.generic)
    )
    everything = not chosen
    status = 0
    estat = Estat()

    if everything or args.generic:
        print("generic")
        report = Report()
        check_generic(report)
        status |= report.show("dades de família dins de tools/")
    if everything or args.xifres:
        print("xifres")
        report = Report()
        check_xifres(estat, report)
        status |= report.show("xifres desfasades")
    if everything or args.rutes:
        print("rutes")
        report = Report()
        check_rutes(estat, report)
        status |= report.show("rutes trencades")
    if everything or args.xrefs:
        print("xrefs")
        report = Report()
        check_xrefs(estat, report)
        status |= report.show("xrefs que anomenen algú altre")
    if everything or args.cr_id:
        print("cr_id")
        report = Report()
        check_cr_id(report)
        status |= report.show("fitxers amb cr_id")
    if everything or args.frontmatter:
        print("frontmatter")
        report = Report()
        fm.check(report, estat.tree)
        status |= report.show("problemes de frontmatter")
    if everything or args.privacitat:
        print("privacitat")
        report = Report()
        check_privacitat(report)
        status |= report.show("problemes de privacitat")
    if args.duplicacio:
        print("duplicació")
        report = Report()
        check_duplicacio(estat, report)
        status |= report.show("problemes")
    if everything or args.informes:
        print("informes")
        report = Report()
        check_informes(estat, report)
        status |= report.show("informes desfasats")

    return status


if __name__ == "__main__":
    sys.exit(main())

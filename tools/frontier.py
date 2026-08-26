"""Rank the research frontier: who to work on next, and where to look.

The frontier is everyone in the canonical tree with no parents recorded. Each
one is classified by what it would actually take to get past them:

  ready       FamilySearch already knows their parents -> import, no research
  stuck       linked to FamilySearch, but FamilySearch is stuck too -> archives
  unknown     linked to FamilySearch, but neither a live pedigree nor the
              committed snapshot says whether it knows the parents -> refetch
  unlinked    not found on FamilySearch yet -> search first

`ready`/`stuck` come from `cache/pedigree.json` when it exists (needs
FamilySearch credentials), and otherwise from `reports/frontier-fs.json`, a
small committed snapshot of just the facts this report prints -- refreshed
automatically whenever the real pedigree is available. Without either, a
person keeps their FSFTID but is `unknown`, never guessed at as `stuck`.

    python3 -m tools.frontier            # write reports/frontier.md
    python3 -m tools.frontier --top 10   # print the top of the queue
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from . import config, frontmatter, report
from .config import tree_path
from .fs.fetch import LiveTree
from .normalize import fold
from .people import Person, Tree

ROOT = Path(__file__).resolve().parents[1]
PEDIGREE = ROOT / "cache" / "pedigree.json"
# The facts this report prints about FamilySearch, not the pedigree itself:
# `cache/pedigree.json` needs credentials to refetch and is not something to
# redistribute, so when it is missing this smaller, committed snapshot is what
# lets `frontier.md` stay accurate without either.
SNAPSHOT = ROOT / "reports" / "frontier-fs.json"
FONTS = ROOT / "Fonts"
REPORTS = ROOT / "reports"

# Which archive holds each town's registers, and how reachable it is, is in
# config.yaml -- `puntuacio:` per region under `guies:`, with `arxius:` for the
# odd town that is an exception. See config.archive_hint.


@lru_cache(maxsize=1)
def _tracked_fonts_files() -> frozenset[Path]:
    """Every file under Fonts/ that git actually tracks.

    Full-resolution scans are deliberately untracked (see `.gitignore`): they
    exist only on whichever machine photographed them. Scanning the filesystem
    instead of git's index makes document corroboration depend on which scans
    happen to be sitting on disk, so the same commit renders a different
    `frontier.md` on a contributor's laptop than in CI's clean checkout --
    `reports/frontier.md`/`worklist.md`, committed here, then fails
    `tools.lint --informes` there no matter how freshly it was regenerated.
    Asking git for the tracked list instead of the filesystem gives the same
    answer wherever the repository is checked out.
    """
    try:
        result = subprocess.run(
            # `-z` and `core.quotePath=false`: without them git prints non-ASCII
            # names (any accented archive folder here) as quoted octal escapes
            # instead of the UTF-8 bytes, which then never matches a real Path.
            ["git", "-c", "core.quotePath=false", "ls-files", "-z", "--", "Fonts"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        # No git available (e.g. a bare export): fall back to the filesystem
        # rather than reporting no documents at all.
        return frozenset(p for p in FONTS.rglob("*") if p.is_file())
    return frozenset(ROOT / line for line in result.stdout.split("\0") if line)


@lru_cache(maxsize=1)
def _tracked_fonts_by_directory() -> dict[Path, list[Path]]:
    """`_tracked_fonts_files()`, grouped by parent directory.

    `_speaks_for`/`_covered_by_declaration` used to call `directory.iterdir()`,
    which only ever touches the handful of files actually in that one folder.
    Filtering the flat `_tracked_fonts_files()` set by `sibling.parent ==
    directory` instead re-scans every tracked file for each declaring document,
    and `documents_for` does that once per person on the frontier: turns a
    sub-second lookup into a cost that grows with tree size squared. Grouping
    once restores the original cost.
    """
    by_dir: dict[Path, list[Path]] = {}
    for path in _tracked_fonts_files():
        by_dir.setdefault(path.parent, []).append(path)
    return by_dir


def slug(text: str) -> str:
    """Filename-ish key: unaccented lowercase words only."""
    decomposed = unicodedata.normalize("NFD", text)
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", plain.lower()))


def index_documents() -> dict[str, list[str]]:
    """Map each document in Fonts/ to its name tokens, for matching against people."""
    out: dict[str, list[str]] = {}
    if not FONTS.exists():
        return out
    for path in sorted(_tracked_fonts_files()):
        if path.name.startswith("."):
            continue
        # Reading copies and the manifest are derived, not documents: indexing
        # them would count the same scan several times over.
        if path.name.endswith("_lectura.jpg") or path.name == "MANIFEST.sha256":
            continue
        stem = path.stem.replace("_", " ")
        # Drop the boilerplate that is not part of a person's name.
        stem = re.sub(
            r"\b(llistats?|genealogia|genealogies|bateig|baptisme|matrimoni|casament|"
            r"defuncio|obit|certificat|registre|partida|expedient|amb|arbol|"
            r"genealogico|apellido|els|les|de|del|la|el|o)\b",
            " ",
            stem,
            flags=re.IGNORECASE,
        )
        tokens = [t for t in slug(stem).split() if len(t) > 2]
        if tokens:
            out[str(path.relative_to(ROOT))] = tokens
    return out


def _close(token: str, candidates: list[str], threshold: float = 0.85) -> bool:
    """Is this name token present, allowing for spelling drift?

    Sources disagree on spellings that mean the same person: an s for a z
    (Ferrandis/Ferrandiz), a Castilianised given name (Vicent/Vicente), a lost
    accent (Agustí/Agustin). A ratio catches those while still refusing
    Josefa/Josep, which are two different people. The threshold is high on
    purpose: it has to be tighter than the surnames of one village are common.
    """
    return any(
        SequenceMatcher(None, token, other).ratio() >= threshold for other in candidates
    )


def declared_documents() -> dict[str, list[str]]:
    """Map each xref to the documents that *declare* it in `xrefs:` frontmatter.

    This is the join done right. Everything below it is a guess from the
    filename, and a guess can credit a person with a document about someone
    else entirely who happens to share a surname. A document that says which
    people it is about does not need guessing.
    """
    out: dict[str, list[str]] = {}
    for path in sorted(p for p in _tracked_fonts_files() if p.suffix == ".md"):
        if ".obsidian" in path.parts:
            continue
        try:
            data = frontmatter.read(path)
        except Exception:  # noqa: BLE001 -- tools.lint --frontmatter reports it properly
            continue
        if not data:
            continue
        relative = str(path.relative_to(ROOT))
        for xref in data.get("xrefs") or []:
            if isinstance(xref, str):
                out.setdefault(xref.strip("@"), []).append(relative)
    return out


def _speaks_for(declared: dict[str, list[str]]) -> dict[str, str]:
    """Map every covered path to the declaring note that speaks for it.

    A scan and its transcription are one document, so a guess about
    `…_1864_detall.png` is a guess about `…_1864.md`. Comparing raw paths would
    report the same disagreement once per attachment.
    """
    out: dict[str, str] = {}
    stems = {
        (str(Path(path).parent), Path(path).stem, path)
        for paths in declared.values()
        for path in paths
    }
    for folder, stem, note in stems:
        directory = ROOT / folder
        for sibling in _tracked_fonts_by_directory().get(directory, ()):
            if sibling.stem.startswith(stem):
                out[str(sibling.relative_to(ROOT))] = note
    return out


def _covered_by_declaration(declared: dict[str, list[str]]) -> set[str]:
    """Every path a declaring note speaks for, including its own attachments.

    A scan sits next to its transcription and shares its stem. They are one
    document, so once the note declares who it is about, the guess must not
    reach the images either: the surname in the filename is the same surname,
    and that is exactly what produces false positives.
    """
    covered: set[str] = set()
    stems = {
        (str(Path(path).parent), Path(path).stem)
        for paths in declared.values()
        for path in paths
    }
    for folder, stem in stems:
        directory = ROOT / folder
        for sibling in _tracked_fonts_by_directory().get(directory, ()):
            if sibling.stem.startswith(stem):
                covered.add(str(sibling.relative_to(ROOT)))
    return covered


def documents_for(
    person: Person,
    docs: dict[str, list[str]],
    declared: dict[str, list[str]] | None = None,
) -> list[str]:
    """Documents in Fonts/ that actually name this person.

    A document that declares `xrefs:` is **taken at its word**: the filename
    guess is not applied to it at all. That is the point of declaring --
    otherwise the guess keeps adding people the document itself does not
    mention, which is how a grandfather can be credited with his grandson's
    baptism because both share a name.

    Only undeclared documents are guessed at, and there the rule stays strict:
    **every** surname must appear, plus the first given name. Anything looser
    produces false corroboration, because in a village the same few surnames
    recur constantly: matching any two tokens can credit a baptism certificate
    to a person's own mother, or to an unrelated person sharing one surname and
    a given name. **A wrongly confirmed filiation is worse than an unconfirmed
    one.**
    """
    declared = declared or {}
    hits = list(declared.get(person.xref, []))
    declaring = _covered_by_declaration(declared)

    surnames = [s for s in person.surname_parts if len(s) > 2]
    givens = [g for g in slug(person.given).split() if len(g) > 2]
    if surnames and givens:
        for path, tokens in docs.items():
            if path in hits or path in declaring:
                continue
            if all(_close(s, tokens) for s in surnames) and _close(givens[0], tokens):
                hits.append(path)
    return hits


def guess_disagreements(
    tree: Tree,
    docs: dict[str, list[str]],
    declared: dict[str, list[str]],
) -> list[tuple[str, str, str]]:
    """Where the filename guess and the declaration do not agree.

    Only documents that declare *someone* are judged: a document with no
    `xrefs:` is undeclared, not contradicted. Each row is (xref, note, which
    side).

    A `només l'heurístic` row is the interesting one: a person the guess
    credited with a document that says, itself, who it is about -- and does
    not say them. Every one of those is a false positive the guess had and
    nothing else could see.
    """
    speaks_for = _speaks_for(declared)
    out: list[tuple[str, str, str]] = []
    for xref, person in tree.people.items():
        mine = set(declared.get(xref, []))
        surnames = [s for s in person.surname_parts if len(s) > 2]
        givens = [g for g in slug(person.given).split() if len(g) > 2]
        guessed: set[str] = set()
        if surnames and givens:
            for path, tokens in docs.items():
                if all(_close(s, tokens) for s in surnames) and _close(
                    givens[0], tokens
                ):
                    # A guess about a scan is a guess about its transcription.
                    guessed.add(speaks_for.get(path, path))
        for note in sorted(guessed & set(speaks_for.values()) - mine):
            out.append((xref, note, "només l'heurístic"))
        for note in sorted(mine - guessed):
            out.append((xref, note, "només declarat"))
    return out


@dataclass
class FrontierEntry:
    person: Person
    status: str  # ready | stuck | unknown | unlinked
    fs_parents: list[Person] = field(default_factory=list)
    upstream: int = 0  # new ancestors reachable above this person
    oldest_upstream: int | None = None
    documents: list[str] = field(default_factory=list)
    # Documents in Fonts/ naming a proposed parent: independent corroboration.
    parent_documents: dict[str, list[str]] = field(default_factory=dict)
    archive: str = ""
    archive_score: int = 0
    score: float = 0.0
    notes: list[str] = field(default_factory=list)


def rank(entry: FrontierEntry) -> float:
    """Higher is more worth doing next."""
    p = entry.person
    score = 0.0

    # A closer generation unlocks more of the direct line.
    generation = p.generation
    if generation:
        score += max(0, 12 - generation) * 1.5
    if p.is_direct_ancestor:
        score += 3.0  # a direct ancestor, not a collateral relative

    # Work already done by someone else is the cheapest work there is.
    if entry.status == "ready":
        score += 10.0
        score += min(entry.upstream, 120) * 0.08
    elif entry.status == "unlinked":
        score -= 2.0  # needs a search before anything else can happen

    # Searchability: a name with a place and a year can actually be looked up.
    if p.birth_town:
        score += 2.0
    if p.birth_year:
        score += 2.0
    if not p.birth_town and not p.birth_year:
        score -= 3.0

    score += entry.archive_score * 0.6
    score += len(entry.documents) * 2.0  # evidence already on disk
    # A certificate naming the proposed parent confirms the link without relying
    # on FamilySearch at all: worth more than a document about the person.
    score += sum(len(v) for v in entry.parent_documents.values()) * 3.0
    return round(score, 2)


def _person_from_snapshot(rec: dict) -> Person:
    """Rebuild the minimal Person a snapshot's `pares` entry describes."""
    given = rec.get("given") or ""
    surname = rec.get("surname") or ""
    return Person(
        xref=rec.get("pid", ""),
        name=f"{given} /{surname}/",
        given=given,
        surname=surname,
        sex=rec.get("sex"),
        birth_date=rec.get("birth_date"),
        birth_place=rec.get("birth_place"),
        death_date=None,
        death_place=None,
        fsftid=rec.get("pid"),
        famc=None,
    )


def snapshot_load(path: Path = SNAPSHOT) -> dict | None:
    """The committed FamilySearch facts, when there is no fresh pedigree."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def snapshot_write(entries: list[FrontierEntry], root: str | None, path: Path = SNAPSHOT) -> Path:
    """Save only what this report prints about FamilySearch, not the pedigree.

    `cache/pedigree.json` cannot be committed: it needs credentials to refetch,
    and FamilySearch's terms don't allow redistributing it. This is smaller and
    different in kind -- the parents already proposed for people in the
    frontier, the same facts `frontier.md` prints in prose -- so it can sit in
    git and let the report stay accurate between logins.
    """
    people: dict[str, dict] = {}
    for e in entries:
        if not e.person.fsftid or e.status not in ("ready", "stuck"):
            continue
        people[e.person.xref] = {
            "fsftid": e.person.fsftid,
            "estat": e.status,
            "amunt": e.upstream,
            "mes_antic": e.oldest_upstream,
            "pares": [
                {
                    "pid": p.xref,
                    "given": p.given,
                    "surname": p.surname,
                    "sex": p.sex,
                    "birth_date": p.birth_date,
                    "birth_place": p.birth_place,
                }
                for p in e.fs_parents
            ],
        }
    configured_root = config.get("familysearch", "arrel")
    data = {
        "data": datetime.date.today().isoformat(),
        "arrel": root or (str(configured_root) if configured_root else ""),
        "persones": people,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def build(
    canon: Tree, live: LiveTree | None, snapshot: dict | None = None
) -> list[FrontierEntry]:
    docs = index_documents()
    declared = declared_documents()
    known_pids = {p.fsftid for p in canon.people.values() if p.fsftid}
    snapshot_people = (snapshot or {}).get("persones", {})
    entries: list[FrontierEntry] = []

    for person in canon.leaves():
        entry = FrontierEntry(person=person, status="unlinked")
        if person.fsftid and live:
            parents = live.parents(person.fsftid)
            if parents:
                entry.status = "ready"
                entry.fs_parents = parents
                # Everything above, excluding people we already have.
                seen = set(known_pids)
                stack, found = [person.fsftid], []
                while stack:
                    for parent in live.parents(stack.pop()):
                        if parent.xref in seen:
                            continue
                        seen.add(parent.xref)
                        found.append(parent)
                        stack.append(parent.xref)
                entry.upstream = len(found)
                years = [q.birth_year for q in found if q.birth_year]
                entry.oldest_upstream = min(years) if years else None
            else:
                entry.status = "stuck"
                entry.notes.append(
                    "FamilySearch també s'atura aquí: cal anar a l'arxiu."
                )
        elif person.fsftid and snapshot_people.get(person.xref, {}).get("fsftid") == person.fsftid:
            # A committed snapshot, from the last time credentials were live.
            # Only trusted when the FSFTID still matches: relinking a person
            # invalidates whatever the snapshot thought it knew.
            record = snapshot_people[person.xref]
            entry.status = record.get("estat", "unknown")
            entry.upstream = record.get("amunt", 0) or 0
            entry.oldest_upstream = record.get("mes_antic")
            entry.fs_parents = [_person_from_snapshot(p) for p in record.get("pares", [])]
            if entry.status == "stuck":
                entry.notes.append(
                    "FamilySearch també s'atura aquí: cal anar a l'arxiu."
                )
        elif person.fsftid:
            # Linked to FamilySearch, but neither a fresh pedigree nor a
            # snapshot can say whether it knows the parents. Not "stuck" --
            # that would be a claim we cannot back up.
            entry.status = "unknown"

        score, text = config.archive_hint(
            person.birth_town, fold(person.birth_place or "")
        )
        entry.archive_score, entry.archive = score, text
        entry.documents = documents_for(person, docs, declared)
        own = set(entry.documents)
        for parent in entry.fs_parents:
            # A document that names the child as well as the parent proves
            # nothing about the link between them, so it is not corroboration.
            hits = [
                d for d in documents_for(parent, docs, declared) if d not in own
            ]
            if hits:
                entry.parent_documents[parent.xref] = hits
        entry.score = rank(entry)
        entries.append(entry)

    entries.sort(key=lambda e: -e.score)
    return entries


def _provenance(entries: list[FrontierEntry], live: LiveTree | None, snapshot: dict | None) -> str:
    """One line saying where the FamilySearch classification came from."""
    if live:
        return "FamilySearch: pedigrí fresc de `cache/pedigree.json`."
    if snapshot:
        covered = sum(1 for e in entries if e.status in ("ready", "stuck"))
        return (
            f"FamilySearch: instantània de `reports/frontier-fs.json`, del "
            f"{snapshot.get('data', '?')} · {covered} de {len(entries)} persones "
            "sense pares hi són cobertes."
        )
    return (
        "FamilySearch: no s'ha pogut consultar (ni `cache/pedigree.json` ni "
        "`reports/frontier-fs.json`). Executa `python -m tools.fs.fetch` per refer-la."
    )


def write_report(
    entries: list[FrontierEntry],
    canon: Tree,
    live: LiveTree | None,
    snapshot: dict | None,
    path: Path,
) -> None:
    ready = [e for e in entries if e.status == "ready"]
    stuck = [e for e in entries if e.status == "stuck"]
    unknown = [e for e in entries if e.status == "unknown"]
    unlinked = [e for e in entries if e.status == "unlinked"]
    importable = sum(e.upstream for e in ready)

    lines = [
        "# Front de recerca",
        "",
        "**Generat per `python -m tools.frontier`. No s'edita a mà.**",
        "",
        _provenance(entries, live, snapshot),
        "",
        f"Persones de l'arbre principal sense pares: **{len(entries)}** de "
        f"{len(canon.people)}.",
        "",
        "| Situació | Persones | Què cal fer |",
        "| --- | --- | --- |",
        f"| A punt d'importar | **{len(ready)}** | FamilySearch ja en sap els pares |",
        f"| Encallades | **{len(stuck)}** | FamilySearch també s'atura aquí: cal arxiu |",
        f"| Sense comprovar | **{len(unknown)}** | Cal `tools.fs.fetch` per saber-ho |",
        f"| Sense enllaçar | **{len(unlinked)}** | Primer cal trobar-les a FamilySearch |",
        "",
        f"Per damunt de les {len(ready)} primeres hi ha **{importable} avantpassats "
        f"nous** disponibles a FamilySearch. L'arbre passaria de "
        f"{len(canon.people)} a unes {len(canon.people) + importable} persones.",
        "",
        "L'ordre suma: generació (com més a prop de qui arrenca l'arbre, més amunt), ser",
        "avantpassat directe i no col·lateral, que FamilySearch ja tingui la feina",
        "feta, tenir lloc i any de naixement per poder cercar, la cobertura de",
        "l'arxiu corresponent i els documents que ja tenim a `Fonts/`.",
        "",
        "---",
        "",
        f"## A punt d'importar ({len(ready)})",
        "",
        "Aquestes no necessiten cap recerca: els pares ja són a FamilySearch. Cal",
        "revisar-los i incorporar-los.",
        "",
    ]
    for e in ready:
        p = e.person
        lines.extend(
            [
                f"### @{p.xref}@ {p.given} {p.surname}"
                f"{f' — G{p.generation}' if p.generation else ''} "
                f"· {e.score} punts",
                "",
                f"- Naixement: {p.birth_date or 'desconegut'}"
                f"{f', {p.birth_town}' if p.birth_town else ''}",
                f"- FamilySearch: [{p.fsftid}]"
                f"(https://www.familysearch.org/tree/person/details/{p.fsftid})",
            ]
        )
        for parent in e.fs_parents:
            role = "Pare" if parent.sex == "M" else "Mare" if parent.sex == "F" else "Progenitor"
            lines.append(
                f"- {role}: **{parent.given} {parent.surname}** "
                f"({parent.birth_date or 'n. ?'}"
                f"{f', {parent.birth_town}' if parent.birth_town else ''}) "
                f"— [{parent.xref}]"
                f"(https://www.familysearch.org/tree/person/details/{parent.xref})"
            )
            # A certificate on disk for the *proposed parent* corroborates the
            # link independently of FamilySearch, which is the strongest signal
            # available here.
            for doc in e.parent_documents.get(parent.xref, ()):
                lines.append(f"  - **Confirmat per un document nostre**: `{doc}`")
        if e.upstream:
            lines.append(
                f"- Per damunt: **{e.upstream} avantpassats** més"
                + (f", fins al {e.oldest_upstream}" if e.oldest_upstream else "")
            )
        for doc in e.documents:
            lines.append(f"- Document que ja tenim: `{doc}`")
        if e.archive:
            lines.append(f"- Arxiu: {e.archive}")
        lines.append("")

    for title, group, blurb in (
        (
            f"Encallades també a FamilySearch ({len(stuck)})",
            stuck,
            "Enllaçades amb FamilySearch, però allà tampoc no en saben els pares. "
            "Aquestes són la recerca de veritat: cal anar als llibres parroquials.",
        ),
        (
            f"Sense comprovar a FamilySearch ({len(unknown)})",
            unknown,
            "Enllaçades amb FamilySearch, però ni el pedigrí ni la instantània diuen "
            "si allà ja en saben els pares. Torna a executar `python -m tools.fs.fetch` "
            "amb credencials per saber-ho.",
        ),
        (
            f"Sense enllaçar amb FamilySearch ({len(unlinked)})",
            unlinked,
            "Encara no s'han trobat a FamilySearch. El primer pas és cercar-les-hi; "
            "després ja es veurà si hi ha ascendència.",
        ),
    ):
        lines.extend([f"## {title}", "", blurb, "",
                      "| Persona | G | Naixement | Lloc | Documents | Arxiu on buscar |",
                      "| --- | --- | --- | --- | --- | --- |"])
        for e in group:
            p = e.person
            docs = ", ".join(f"`{Path(d).name}`" for d in e.documents) or "—"
            lines.append(
                f"| @{p.xref}@ {p.given} {p.surname} | {p.generation or '—'} "
                f"| {p.birth_date or '?'} | {p.birth_town or '?'} | {docs} "
                f"| {e.archive or '—'} |"
            )
        lines.append("")

    report.write(path, "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--pedigree", default=PEDIGREE)
    parser.add_argument("--snapshot", default=SNAPSHOT)
    parser.add_argument("--top", type=int, help="print the top N and exit")
    parser.add_argument(
        "--discrepancies",
        action="store_true",
        help="where the filename guess and the declared xrefs disagree",
    )
    args = parser.parse_args()

    canon = Tree(args.canonical or tree_path())
    live = None
    path = Path(args.pedigree)
    if path.exists():
        live = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))
    else:
        print(f"no pedigree at {path}; falling back to reports/frontier-fs.json", file=sys.stderr)

    snapshot_path = Path(args.snapshot)
    snapshot = None if live else snapshot_load(snapshot_path)
    if not live and not snapshot:
        print(f"no snapshot at {snapshot_path} either; FamilySearch status will be unknown",
              file=sys.stderr)

    if args.discrepancies:
        docs, declared = index_documents(), declared_documents()
        rows = guess_disagreements(canon, docs, declared)
        for xref, document, side in rows:
            person = canon.people[xref]
            print(f"  {side:18} @{xref}@ {person.given} {person.surname}")
            print(f"  {'':18} {document}")
        guessed_only = sum(1 for _, _, side in rows if side == "només l'heurístic")
        print(
            f"\n{len(rows)} discrepàncies: {guessed_only} que només diu l'heurístic "
            f"—cada una és un fals positiu seu— i {len(rows) - guessed_only} que "
            "només sap el document."
        )
        return 0

    entries = build(canon, live, snapshot)

    if live:
        written = snapshot_write(entries, live.root, snapshot_path)
        print(f"wrote {written.relative_to(ROOT)}")

    if args.top:
        for e in entries[: args.top]:
            p = e.person
            print(
                f"{e.score:6.2f}  {e.status:9s} @{p.xref}@ {p.given} {p.surname} "
                f"(G{p.generation or '?'}, {p.birth_town or 'lloc desconegut'})"
                + (f" -> {e.upstream} amunt" if e.upstream else "")
            )
        return 0

    REPORTS.mkdir(exist_ok=True)
    write_report(entries, canon, live, snapshot, REPORTS / "frontier.md")
    counts = {
        s: sum(1 for e in entries if e.status == s)
        for s in ("ready", "stuck", "unknown", "unlinked")
    }
    print(
        f"{len(entries)} dead-ends: {counts['ready']} ready, {counts['stuck']} stuck, "
        f"{counts['unknown']} unknown, {counts['unlinked']} unlinked"
    )
    print(f"{sum(e.upstream for e in entries)} ancestors importable from FamilySearch")
    print("wrote reports/frontier.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

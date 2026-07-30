"""Rank the research frontier: who to work on next, and where to look.

The frontier is everyone in the canonical tree with no parents recorded. Each
one is classified by what it would actually take to get past them:

  ready       FamilySearch already knows their parents -> import, no research
  stuck       linked to FamilySearch, but FamilySearch is stuck too -> archives
  unlinked    not found on FamilySearch yet -> search first

    python3 -m tools.frontier            # write reports/frontier.md
    python3 -m tools.frontier --top 10   # print the top of the queue
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from . import config
from .config import tree_path
from .fs.fetch import LiveTree
from .normalize import fold
from .people import Person, Tree

ROOT = Path(__file__).resolve().parents[1]
PEDIGREE = ROOT / "cache" / "pedigree.json"
FONTS = ROOT / "Fonts"
REPORTS = ROOT / "reports"

# Which archive holds each town's registers, and how reachable it is, is in
# config.yaml -- `puntuacio:` per region under `guies:`, with `arxius:` for the
# odd town that is an exception. See config.archive_hint.


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
    for path in sorted(FONTS.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
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

    The sources disagree on spellings that mean the same person: an s for a z
    (Ferrandis/Ferrandiz), a Castilianised given name (Vicent/Vicente), a lost
    accent (Agustí/Agustin). A ratio catches those while still refusing
    Josefa/Josep, which are two different people. The threshold is high on
    purpose: it has to be tighter than the surnames of one village are common.
    """
    return any(
        SequenceMatcher(None, token, other).ratio() >= threshold for other in candidates
    )


def documents_for(person: Person, docs: dict[str, list[str]]) -> list[str]:
    """Documents in Fonts/ that actually name this person.

    Requires **every** surname to appear, plus the first given name. Anything
    looser produces false corroboration, because in one village the same few
    surnames recur constantly and the two surnames often appear in both orders:
    matching any two tokens credited a man's baptism certificate to his own
    mother, whose maiden surnames were his in reverse, and credited another
    baptism to an unrelated woman sharing one surname and a given name.

    **A wrongly confirmed filiation is worse than an unconfirmed one.**
    """
    surnames = [s for s in person.surname_parts if len(s) > 2]
    givens = [g for g in slug(person.given).split() if len(g) > 2]
    if not surnames or not givens:
        return []
    hits = []
    for path, tokens in docs.items():
        if all(_close(s, tokens) for s in surnames) and _close(givens[0], tokens):
            hits.append(path)
    return hits


@dataclass
class FrontierEntry:
    person: Person
    status: str  # ready | stuck | unlinked
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


def build(canon: Tree, live: LiveTree | None) -> list[FrontierEntry]:
    docs = index_documents()
    known_pids = {p.fsftid for p in canon.people.values() if p.fsftid}
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
        elif person.fsftid:
            entry.status = "stuck"

        score, text = config.archive_hint(
            person.birth_town, fold(person.birth_place or "")
        )
        entry.archive_score, entry.archive = score, text
        entry.documents = documents_for(person, docs)
        own = set(entry.documents)
        for parent in entry.fs_parents:
            # A document that names the child as well as the parent proves
            # nothing about the link between them, so it is not corroboration.
            hits = [d for d in documents_for(parent, docs) if d not in own]
            if hits:
                entry.parent_documents[parent.xref] = hits
        entry.score = rank(entry)
        entries.append(entry)

    entries.sort(key=lambda e: -e.score)
    return entries


def write_report(entries: list[FrontierEntry], canon: Tree, live: LiveTree | None, path: Path) -> None:
    ready = [e for e in entries if e.status == "ready"]
    stuck = [e for e in entries if e.status == "stuck"]
    unlinked = [e for e in entries if e.status == "unlinked"]
    importable = sum(e.upstream for e in ready)

    lines = [
        "# Front de recerca",
        "",
        f"Persones de l'arbre principal sense pares: **{len(entries)}** de "
        f"{len(canon.people)}.",
        "",
        "| Situació | Persones | Què cal fer |",
        "| --- | --- | --- |",
        f"| A punt d'importar | **{len(ready)}** | FamilySearch ja en sap els pares |",
        f"| Encallades | **{len(stuck)}** | FamilySearch també s'atura aquí: cal arxiu |",
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

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--pedigree", default=PEDIGREE)
    parser.add_argument("--top", type=int, help="print the top N and exit")
    args = parser.parse_args()

    canon = Tree(args.canonical or tree_path())
    live = None
    path = Path(args.pedigree)
    if path.exists():
        live = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))
    else:
        print(f"no pedigree at {path}; run tools.fs.fetch first", file=sys.stderr)

    entries = build(canon, live)

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
    write_report(entries, canon, live, REPORTS / "frontier.md")
    counts = {s: sum(1 for e in entries if e.status == s) for s in ("ready", "stuck", "unlinked")}
    print(
        f"{len(entries)} dead-ends: {counts['ready']} ready, {counts['stuck']} stuck, "
        f"{counts['unlinked']} unlinked"
    )
    print(f"{sum(e.upstream for e in entries)} ancestors importable from FamilySearch")
    print("wrote reports/frontier.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

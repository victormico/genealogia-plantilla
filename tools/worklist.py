"""Worklists for the archives that have no API.

Everyone FamilySearch cannot resolve -- the ones it has but has no parents
for, and the ones it has never heard of -- needs actual archive work. Few of
those archives offer an API or bulk access, and FamilySearch's terms prohibit
scraping their site, so this generates a checklist of direct search links to work
through by hand rather than pretending to automate it.

Which archive each person belongs to comes from `regions:` in config.yaml, and
what to know before going there from `guies:`.

    python3 -m tools.worklist              # reports/worklist.md
    python3 -m tools.worklist --region girona
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import quote_plus

from . import config, report
from .config import tree_path
from .frontier import FrontierEntry, SNAPSHOT, build, snapshot_load
from .fs.fetch import LiveTree
from .normalize import fold
from .people import Tree

from .config import ROOT
PEDIGREE = ROOT / "cache" / "pedigree.json"
REPORTS = ROOT / "reports"

# Which cluster each town belongs to, and what is worth knowing about each
# archive, both come from config.yaml. They are the part of this tool that is
# different for every family, so they are not in the code. See `regions:`,
# `regions_per_defecte:` and `guies:` there.
UNPLACED = config.UNPLACED


def region_of(entry: FrontierEntry) -> str:
    """Which archive cluster to go looking for this person in.

    Delegated to config so that this and the frontier ranking cannot drift
    apart: they used to keep two copies of the town lists between them.
    """
    return config.region_for(
        entry.person.birth_town, fold(entry.person.birth_place or "")
    )


def search_links(entry: FrontierEntry) -> list[tuple[str, str]]:
    """Direct searches to run for one person."""
    p = entry.person
    given = (p.given or "").split(",")[0].strip()
    links: list[tuple[str, str]] = []

    # FamilySearch record search, prefilled. Their terms permit using the site;
    # what they prohibit is scraping it, so we hand over a link, not a crawler.
    params = [f"q.surname={quote_plus(p.surname)}"]
    if given:
        params.append(f"q.givenName={quote_plus(given)}")
    if p.birth_place:
        params.append(f"q.birthLikePlace={quote_plus(p.birth_place)}")
    if p.birth_year:
        params.append(f"q.birthLikeDate.from={p.birth_year - 3}")
        params.append(f"q.birthLikeDate.to={p.birth_year + 3}")
    links.append(
        ("Cerca de registres a FamilySearch", "https://www.familysearch.org/search/record/results?" + "&".join(params))
    )
    if p.fsftid:
        links.append(
            ("Fitxa a l'arbre de FamilySearch", f"https://www.familysearch.org/tree/person/details/{p.fsftid}")
        )
    else:
        links.append(
            (
                "Cerca a l'arbre de FamilySearch",
                "https://www.familysearch.org/tree/find/name?search=1&"
                f"self=%7B%22surname%22%3A%22{quote_plus(p.surname)}%22%7D",
            )
        )
    return links


def _provenance(live: LiveTree | None, snapshot: dict | None) -> str:
    """One line saying where the FamilySearch classification came from."""
    if live:
        return "FamilySearch: pedigrí fresc de `cache/pedigree.json`."
    if snapshot:
        return (
            f"FamilySearch: instantània de `reports/frontier-fs.json`, del "
            f"{snapshot.get('data', '?')}."
        )
    return (
        "FamilySearch: no s'ha pogut consultar (ni `cache/pedigree.json` ni "
        "`reports/frontier-fs.json`). Executa `python -m tools.fs.fetch` per refer-la."
    )


def write_report(
    entries: list[FrontierEntry],
    path: Path,
    live: LiveTree | None = None,
    snapshot: dict | None = None,
    only: str | None = None,
) -> None:
    grouped: dict[str, list[FrontierEntry]] = {}
    for entry in entries:
        if entry.status == "ready":
            continue  # nothing to research: FamilySearch already has the answer
        grouped.setdefault(region_of(entry), []).append(entry)

    guides = config.region_guides()
    # The order the guides are written in the config, with the placeless last:
    # whoever wrote the config put the archive they work most first.
    order = [n for n in guides if n != UNPLACED] + [UNPLACED]
    # A region that has people but no guide still has to appear, or the report
    # would quietly drop them.
    order += [n for n in grouped if n not in order]
    total = sum(len(v) for k, v in grouped.items() if not only or k == only)

    lines = [
        "# Llista de feina als arxius",
        "",
        "**Generat per `python -m tools.worklist`. No s'edita a mà.**",
        "",
        _provenance(live, snapshot),
        "",
        f"**{total} persones** que FamilySearch no pot resoldre, agrupades per",
        "l'arxiu on cal anar a buscar-les.",
        "",
        "Cap d'aquests arxius no té API ni descàrrega massiva, i les condicions d'ús",
        "de FamilySearch prohibeixen rastrejar-ne el web. Per això això és una llista",
        "d'enllaços per obrir a mà i no un programa que ho faci sol.",
        "",
        "| Zona | Persones |",
        "| --- | --- |",
    ]
    for name in order:
        if name in grouped and (not only or name == only):
            lines.append(f"| {guides.get(name, {}).get('title', name)} | {len(grouped[name])} |")
    lines.append("")

    for name in order:
        group = grouped.get(name)
        if not group or (only and name != only):
            continue
        guide = guides.get(name) or {"title": name, "blurb": "", "links": [], "extra": ""}
        lines.extend(["---", "", f"## {guide['title']}", "", guide["blurb"], ""])
        if guide["links"]:
            lines.append("**Punts de partida**")
            lines.append("")
            for label, url in guide["links"]:
                lines.append(f"- [{label}]({url})")
            lines.append("")
        if guide["extra"]:
            lines.extend([guide["extra"], ""])

        lines.append(f"### Persones a buscar ({len(group)})")
        lines.append("")
        for entry in sorted(group, key=lambda e: -e.score):
            p = entry.person
            head = f"#### {p.given} {p.surname} — @{p.xref}@"
            if p.generation:
                head += f" · generació {p.generation}"
            lines.extend([head, ""])
            facts = []
            if p.birth_date:
                facts.append(f"nascut/da el {p.birth_date}")
            elif p.birth_year:
                facts.append(f"nascut/da cap al {p.birth_year}")
            if p.birth_town:
                facts.append(f"a {p.birth_town}")
            if p.death_date:
                facts.append(f"mort/a el {p.death_date}")
            lines.append(f"- {', '.join(facts) if facts else 'sense dates ni lloc'}")
            if entry.status == "stuck":
                lines.append("- FamilySearch la té però no en sap els pares")
            elif entry.status == "unknown":
                lines.append(
                    "- Enllaçada amb FamilySearch, però no s'ha pogut comprovar si en "
                    "sap els pares (cal `python -m tools.fs.fetch`)"
                )
            else:
                lines.append("- Encara no s'ha trobat a FamilySearch")
            for doc in entry.documents:
                lines.append(f"- Document que ja tenim: `{doc}`")
            for label, url in search_links(entry):
                lines.append(f"- [{label}]({url})")
            lines.append("")

    report.write(path, "\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--pedigree", default=PEDIGREE)
    parser.add_argument("--snapshot", default=SNAPSHOT)
    parser.add_argument("--region", choices=sorted(config.region_guides()),
                        help="només aquesta regió")
    args = parser.parse_args()

    canon = Tree(args.canonical or tree_path())
    live = None
    path = Path(args.pedigree)
    if path.exists():
        live = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))

    snapshot_path = Path(args.snapshot)
    snapshot = None if live else snapshot_load(snapshot_path)

    entries = build(canon, live, snapshot)
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "worklist.md"
    write_report(entries, out, live, snapshot, args.region)

    guides = config.region_guides()
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.status != "ready":
            counts[region_of(entry)] = counts.get(region_of(entry), 0) + 1
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3d}  {guides.get(name, {}).get('title', name)}")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

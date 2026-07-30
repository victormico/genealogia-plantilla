"""Bottom-up verification: check a line of descent against the diocesan index.

A run of ancestors that all rest on one secondary source -- a family summary, a
published genealogy, somebody else's tree -- is a run of guesses until a document
says otherwise. This walks that line **from the bottom up**, from the last person
a document actually confirms upward, and works out for each one whether the index
can settle it and with which sacrament.

Bottom-up is the right direction for a reason. If the nearest unverified
generation turns out wrong, nothing above it is worth a query; verifying downward
from the oldest name would spend the day's fifteen on the least certain end.

Where the documented ground ends is `apv: terra_documentada:` in config.yaml.
Left blank, this starts from the de-cujus (Sosa 1) and checks the whole line.

    python3 -m tools.apv.verify                  # the plan, no requests
    python3 -m tools.apv.verify --quota          # how many queries are left today
    python3 -m tools.apv.verify --top 5 --fetch  # actually look up the first five

Without `--fetch` this makes no requests at all.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import config
from ..config import tree_path
from ..people import Tree
from . import coverage
from . import query
from .query import Lookup, SELECTIVE, url
from .session import Challenged, QuotaExhausted, add_common_args, build_session

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports" / "apv-verificacio.md"


def documented_floor(tree: Tree) -> str | None:
    """The deepest person a document already confirms: where to start climbing.

    Explicit in the config rather than derived, because the point of naming it
    is to state where documented ground ends -- that is a judgement about
    evidence, and no amount of reading the GEDCOM will produce it.

    Falling back to Sosa 1 keeps the tool usable on day one: it then plans the
    whole direct line instead of the unverified tail, which is more queries than
    you have but a perfectly good map.
    """
    floor = config.apv_floor()
    if floor:
        floor = floor.strip("@")
        if floor not in tree.people:
            raise SystemExit(
                f"el config.yaml diu «terra_documentada: {floor}» i aquesta persona "
                "no és a l'arbre. Fa servir l'identificador que porta el GEDCOM, "
                "de la forma I00042."
            )
        return floor
    for xref, person in tree.people.items():
        if person.sosa and person.sosa.split()[0] == "1":
            return xref
    return next(iter(tree.people), None)


def plan(tree: Tree) -> list[Lookup]:
    """One ranked lookup per person, cheapest and most decisive first."""
    floor = documented_floor(tree)
    if floor is None:
        return []
    spine = _spine_upwards(tree, floor)
    out: list[Lookup] = []

    for depth, person in enumerate(spine):
        spouses = tree.spouses(person.xref)
        parents = tree.parents(person.xref)
        parish = _parish_of(person, tree)

        # A marriage fiche gives the searched person's parents AND four
        # grandparents, and Ontinyent marriages are complete 1560-1900 where the
        # baptisms have two big holes. So marriage first, always.
        for spouse in spouses or [None]:
            year = _marriage_year(person, spouse, tree)
            verdict = coverage.covers(parish, coverage.MARRIAGE, year)
            settles = (
                f"donaria els pares i els quatre avis de {person.given}"
                if not parents else
                f"confirmaria o desmentiria {', '.join(p.given + ' ' + p.surname for p in parents)}"
            )
            out.append(Lookup(
                xref=person.xref, who=_label(person),
                sacrament=coverage.MARRIAGE, parish=parish, year=year,
                what_it_would_settle=settles,
                url=url(given=person.given, surname=_first(person.surname),
                        surname2=_second(person.surname),
                        spouse_surname=_first(spouse.surname) if spouse else "",
                        event_place=parish,
                        sacrament=query.MARRIAGE,
                        # A ±8 year window: the year is an estimate, so pinning
                        # it exactly would hide the real record.
                        event_from=year - 8 if year else "",
                        event_to=year + 8 if year else ""),
                possible=bool(verdict), note=verdict.why,
                rank=depth * 10,
                terms={"nom": person.given, "a1": _first(person.surname),
                       "cognomcj": _first(spouse.surname) if spouse else ""},
            ))

        # Then the baptism, which is the direct evidence for the person's own
        # parents when the years fall inside a covered span.
        byear = person.birth_year
        verdict = coverage.covers(parish, coverage.BAPTISM, byear)
        out.append(Lookup(
            xref=person.xref, who=_label(person),
            sacrament=coverage.BAPTISM, parish=parish, year=byear,
            what_it_would_settle=f"la seva pròpia partida: pares i quatre avis de {person.given}",
            url=url(given=person.given, surname=_first(person.surname),
                    surname2=_second(person.surname), event_place=parish,
                    sacrament=query.BAPTISM,
                    event_from=byear - 2 if byear else "",
                    event_to=byear + 2 if byear else ""),
            possible=bool(verdict), note=verdict.why,
            rank=depth * 10 + 1,
            terms={"nom": person.given, "a1": _first(person.surname)},
        ))

    out.sort(key=lambda l: (not l.possible, l.rank))
    return out


def render(lookups: list[Lookup], quota: str) -> str:
    doable = [l for l in lookups if l.possible]
    blocked = [l for l in lookups if not l.possible]
    lines = [
        "# Verificació de baix a dalt contra l'índex diocesà",
        "",
        "Generat per `python3 -m tools.apv.verify`. **Aquest fitxer es regenera**; el",
        "raonament va als fitxers de cas.",
        "",
        f"**{quota}**",
        "",
        f"De les {len(lookups)} comprovacions possibles sobre paper, **{len(doable)} es poden",
        f"demanar de veres** i {len(blocked)} no, perquè cauen en un forat de l'índex o en",
        "l'embargament legal. L'ordre és de baix a dalt: **si un graó falla, els de damunt",
        "no valen una consulta.**",
        "",
        "> **Que l'índex tinga l'apunt no vol dir que el llibre tinga la partida.**",
        "> L'índex és un fitxer de referències: diu llibre, foli i número. Amb això a",
        "> la mà, el manuscrit es demana a l'Arxiu Diocesà de València, i de vegades",
        "> resulta que el foli no hi és o que el llibre s'ha perdut.",
        "",
        f"Cerca selectiva, per si vols escriure-hi a mà: <{SELECTIVE}>",
        "",
        "## Es poden demanar, per ordre",
        "",
    ]
    for n, l in enumerate(doable, 1):
        lines += [f"### {n}. {l.line()}", ""]
    lines += ["## No es poden demanar, i per què", ""]
    for l in blocked:
        year = l.year if l.year is not None else "?"
        lines.append(f"- **{l.who}** — {l.sacrament} {year}, {l.parish}: {l.note}")
    lines += [
        "",
        "### Què fer amb els que no es poden demanar",
        "",
        "**Quan el bateig cau en un forat, el camí és el matrimoni.** Una fitxa de",
        "matrimoni dona els pares *i* els quatre avis de la persona buscada, o siga que",
        "per a filiació val igual o més que un bateig, i als llibres de matrimonis els",
        "solen faltar menys anys. La cobertura de cada parròquia és a",
        "`tools/apv/coverage.py`, i preguntar-li-ho no gasta cap consulta.",
        "",
        "El que això no arregla és el que va per damunt d'on comencen els llibres. Cap",
        "sagrament no hi arriba, i l'índex tampoc: es demana a l'arxiu, o es queda obert",
        "al fitxer de cas.",
        "",
        "#### Cobertura de les parròquies que hi surten",
        "",
        "| Parròquia | Bateigs | Matrimonis | Defuncions |",
        "| --- | --- | --- | --- |",
    ]
    for parish in sorted({l.parish for l in lookups if l.parish}):
        key = coverage._parish_key(parish)
        spans = []
        for sacrament in (coverage.BAPTISM, coverage.MARRIAGE, coverage.DEATH):
            ranges = coverage.COVERAGE.get(key, {}).get(sacrament) or [] if key else []
            spans.append(", ".join(f"{a}-{b}" for a, b in ranges) or "—")
        lines.append(f"| {parish} | {spans[0]} | {spans[1]} | {spans[2]} |")
    lines.append("")
    return "\n".join(lines)


def _spine_upwards(tree: Tree, floor: str) -> list:
    """From the documented floor upward along the paternal line."""
    out, seen, current = [], set(), floor
    while current and current not in seen:
        seen.add(current)
        person = tree.people.get(current)
        if person is None:
            break
        out.append(person)
        parents = tree.parents(current)
        father = next((p for p in parents if (p.sex or "M") == "M"), None)
        current = father.xref if father else None
    return out


def _label(person) -> str:
    sosa = f", Sosa {person.sosa.split()[0]}" if person.sosa else ""
    year = person.birth_year or "?"
    return f"{person.given} {person.surname} ({year}{sosa}) @{person.xref}@"


def _parish_of(person, tree: Tree) -> str:
    """Where the sacrament would have been recorded.

    Careful: **a birth place is not a parish**, and the two diverge on purpose.
    A hamlet with no church of its own has its baptisms in the mother parish's
    books until the year it got its own, so the rules in `apv: parroquies:` can
    redirect by year. Getting this wrong searches the wrong books and reports a
    real record as missing.

    When the person's own place says nothing, the places of the people around
    them usually do: a spouse or a parent born in the parish is good enough to
    aim a query that would otherwise not happen at all.
    """
    rules = config.apv_parish_rules()
    year = person.birth_year

    def match(place: str) -> str | None:
        text = (place or "").lower()
        if not text:
            return None
        for rule in rules:
            needles = rule.get("si_el_lloc_conte") or []
            if isinstance(needles, str):
                needles = [needles]
            if not any(str(n).lower() in text for n in needles):
                continue
            before = rule.get("abans_de")
            if before and year and year < int(before):
                return str(rule.get("llavors") or rule.get("parroquia", ""))
            return str(rule.get("parroquia", ""))
        return None

    found = match(person.birth_place)
    if found:
        return found
    for other in tree.spouses(person.xref) + tree.parents(person.xref):
        found = match(other.birth_place)
        if found:
            return found
    return config.apv_default_parish()


def _marriage_year(person, spouse, tree: Tree | None = None) -> int | None:
    """When there is no MARR event to read, estimate. Carefully.

    **The trap, and it bit on the first run of this**: the obvious anchor is the
    eldest known child, but AN ANCESTOR-ONLY TREE HAS NO SIBLINGS IN IT. The one
    child recorded for a couple is whichever one you descend from, and that is
    rarely the firstborn. Anchoring on it put one wedding twenty-two years late,
    because the seven siblings are not in the file and the ancestor is the fourth.

    Twenty-two years is not a harmless error. Against an index whose coverage
    comes in twenty-year spans, that size of drift flips the verdict from
    "covered" to "gap" -- wasting a query, or worse, skipping a possible one.

    So: birth + `edat_de_casar` as the estimate, and the eldest recorded child
    only as a **ceiling** -- they certainly married before that child was born.
    """
    marriage_age = config.marriage_age()
    child_years = [
        c.birth_year for c in (tree.children(person.xref) if tree else []) if c.birth_year
    ]
    ceiling = min(child_years) - 1 if child_years else None

    from_age = None
    if person.birth_year:
        from_age = person.birth_year + marriage_age
    elif spouse is not None and spouse.birth_year:
        from_age = spouse.birth_year + marriage_age - 2

    if from_age is not None and ceiling is not None:
        return min(from_age, ceiling)
    return from_age if from_age is not None else ceiling


def _first(surname: str) -> str:
    return (surname or "").split()[0] if surname else ""


def _second(surname: str) -> str:
    parts = (surname or "").split()
    return parts[1] if len(parts) > 1 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--gedcom", default=None)
    parser.add_argument("--top", type=int, default=0,
                        help="amb --fetch, quantes consultes fer com a màxim")
    parser.add_argument("--fetch", action="store_true",
                        help="demana de veres les primeres --top consultes")
    args = parser.parse_args()

    session = build_session(args)
    for what in getattr(args, "record", []) or []:
        session.quota.spend(f"[navegador] {what}")
        print(f"apuntada: {what}")
    if args.quota or (getattr(args, "record", []) and not args.fetch):
        print(session.quota.summary())
        return 0

    tree = Tree(args.gedcom or tree_path())
    lookups = plan(tree)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(lookups, session.quota.summary()), encoding="utf-8")
    doable = [l for l in lookups if l.possible]
    print(f"{len(lookups)} comprovacions, {len(doable)} demanables -> {REPORT.relative_to(ROOT)}")
    print(session.quota.summary())

    if not args.fetch:
        print("cap petició feta. Passa --fetch --top N per demanar-ne unes quantes.")
        return 0

    budget = min(args.top or 0, session.quota.remaining())
    if budget <= 0:
        print("res a demanar: o --top és 0 o no queden consultes avui.")
        return 0

    from .parse import parse_results, quota_line

    for l in doable[:budget]:
        print(f"\n-> {l.who}: {l.sacrament} {l.year}, {l.parish}")
        try:
            page = session.get(l.url, why=f"{l.xref} {l.sacrament} {l.year}")
        except QuotaExhausted as exc:
            print(f"  ATURAT: {exc}")
            break
        except Challenged as exc:
            print(f"  ATURAT: {exc}")
            print("\n  Les URL són al report; obri-les al navegador i desa la pàgina.")
            print("  Després: parse.parse_fiche(html) i parse.to_markdown(...).")
            break
        if not page:
            continue
        note = quota_line(page)
        if note:
            print(f"  l'arxiu diu: {note}")
        hits = parse_results(page)
        print(f"  {len(hits)} referència(es)")
        for h in hits[:6]:
            print(f"    · {h['book']} ({h['from']}-{h['to']}) foli {h['folio']} {h.get('registro','')}")
    print(f"\n{session.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

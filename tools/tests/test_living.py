"""Acceptance tests for the presumed-living rule and the section it feeds.

The regression this file pins: `reports/frontier.md` used to list the living
in `Sense enllaçar amb FamilySearch`, under "the first step is to search for
them there", with a parish archive named in the last column -- next to
16th-century ancestors, and counted in the same total. Every part of that was
wrong: FamilySearch hides living people, the registers are closed by law, and
the total made the research look bigger than it was.

    python3 -m tools.tests.test_living
"""

from __future__ import annotations

import datetime
import sys
import tempfile
from pathlib import Path

from tools.config import example_tree
from tools.frontier import build, write_report
from tools.living import GENERATION, estimated_births, presumed_living
from tools.people import Tree
from tools.worklist import write_report as worklist_write_report

CANONICAL = example_tree()

# exemple.ged's two leaves born within the threshold, both with no death
# recorded: the grandmothers the report used to send somebody to an archive for.
LIVING_LEAVES = {"I00005", "I00007"}

# Fixed so the tests do not start failing on a birthday. The tree's living
# leaves were born in 1945 and 1948, so any "today" in this decade gives the
# same answer; pinning it says so out loud.
TODAY = datetime.date(2026, 1, 1)

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_who_counts_as_living(canon: Tree) -> None:
    print("\nqui compta com a contemporani")
    verdicts = presumed_living(canon, today=TODAY)
    leaves = {p.xref for p in canon.leaves()}
    check(
        set(verdicts) & leaves == LIVING_LEAVES,
        "els dos sense pares nascuts fa menys de 100 anys",
        f"{sorted(set(verdicts) & leaves)}",
    )
    check(
        all(
            not (canon.people[x].death_date or canon.people[x].death_place)
            for x in verdicts
        ),
        "mai algú amb defunció apuntada",
    )
    check(
        all("nascut/da el" in v.reason or "estimat" in v.reason for v in verdicts.values()),
        "cada veredicte diu per què",
    )


def test_a_recorded_death_always_wins(canon: Tree) -> None:
    """A burial outranks the arithmetic, however recent the birth."""
    print("\nuna defunció apuntada mana per damunt de l'aritmètica")
    tree = Tree(CANONICAL)
    xref = sorted(LIVING_LEAVES)[0]
    tree.people[xref].death_date = "3 MAR 2020"
    check(
        xref not in presumed_living(tree, today=TODAY),
        "amb defunció, ja no és contemporani",
    )


def test_the_threshold_is_the_only_number(canon: Tree) -> None:
    print("\nel llindar és l'únic número que hi decideix")
    check(
        not presumed_living(canon, limit=1, today=TODAY),
        "amb llindar 1 any, ningú no és contemporani",
    )
    check(
        len(presumed_living(canon, limit=500, today=TODAY))
        >= len(presumed_living(canon, today=TODAY)),
        "amb un llindar més ample, mai no en surten menys",
    )


def test_a_year_is_inherited_from_relatives(canon: Tree) -> None:
    """Somebody with no dates takes the year of the nearest relative who has one."""
    print("\nqui no té dates hereta l'any dels parents")
    tree = Tree(CANONICAL)
    xref = sorted(LIVING_LEAVES)[0]
    person = tree.people[xref]
    own_year = person.birth_year
    spouses = tree.spouses(xref)
    person.birth_date = None
    estimate = estimated_births(tree).get(xref)
    check(estimate is not None, "en surt una estimació")
    if estimate is not None:
        check(estimate.steps > 0, "i diu que no és una data seva", f"steps={estimate.steps}")
        check(
            abs(estimate.year - (own_year or 0)) <= GENERATION,
            "a una generació de la data real",
            f"estimat {estimate.year}, real {own_year}",
        )
        check(
            any(s.given in estimate.basis for s in spouses if s.given)
            or estimate.basis != "",
            "i diu de qui l'ha tret",
            estimate.basis,
        )
    check(
        xref in presumed_living(tree, today=TODAY),
        "i encara compta com a contemporani",
    )


def test_an_undated_branch_claims_nothing(canon: Tree) -> None:
    """No date anywhere near somebody is not a reason to call them alive."""
    print("\nsense cap data a la branca, no es diu res")
    tree = Tree(CANONICAL)
    for person in tree.people.values():
        person.birth_date = None
        person.death_date = None
        person.death_place = None
    check(
        not presumed_living(tree, today=TODAY),
        "un arbre sense cap data no té cap contemporani",
    )


def test_they_leave_the_research_queue(canon: Tree) -> None:
    print("\nsurten de la cua de recerca")
    entries = build(canon, None, None)
    by_xref = {e.person.xref: e for e in entries}
    for xref in LIVING_LEAVES:
        entry = by_xref[xref]
        check(entry.status == "living", f"@{xref}@ és «living»", entry.status)
        check(entry.score == 0.0, f"@{xref}@ no es puntua", str(entry.score))
        check(
            entry.archive == "",
            f"@{xref}@ no porta cap arxiu on anar",
            entry.archive,
        )
    check(
        all(e.status != "unlinked" for x, e in by_xref.items() if x in LIVING_LEAVES),
        "cap no queda a «sense enllaçar»",
    )


def test_the_reports_separate_them(canon: Tree) -> None:
    print("\nels informes els mostren a part")
    entries = build(canon, None, None)
    with tempfile.TemporaryDirectory() as tmp:
        frontier_path = Path(tmp) / "frontier.md"
        worklist_path = Path(tmp) / "worklist.md"
        write_report(entries, canon, None, None, frontier_path)
        worklist_write_report(entries, worklist_path)
        frontier = frontier_path.read_text(encoding="utf-8")
        worklist = worklist_path.read_text(encoding="utf-8")

    head, _, tail = frontier.partition("## Persones contemporànies")
    check(bool(tail), "frontier.md té l'apartat «Persones contemporànies»")
    for xref in LIVING_LEAVES:
        check(f"@{xref}@" in tail, f"@{xref}@ hi és")
        check(f"@{xref}@" not in head, f"@{xref}@ no surt enlloc més de frontier.md")
        check(f"@{xref}@" not in worklist, f"@{xref}@ no surt a worklist.md")
    check(
        "familysearch.org/search/record" not in tail,
        "cap enllaç de cerca de registres per a una persona viva",
    )
    check(
        f"**{len(LIVING_LEAVES)} persones contemporànies**" in worklist,
        "worklist.md diu quantes n'ha deixat fora",
    )
    check(
        tail.rstrip().endswith("`config.yaml`."),
        "i l'apartat va al final, que és on no destorba",
    )


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    canon = Tree(CANONICAL)

    test_who_counts_as_living(canon)
    test_a_recorded_death_always_wins(canon)
    test_the_threshold_is_the_only_number(canon)
    test_a_year_is_inherited_from_relatives(canon)
    test_an_undated_branch_claims_nothing(canon)
    test_they_leave_the_research_queue(canon)
    test_the_reports_separate_them(canon)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

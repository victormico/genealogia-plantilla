"""Offline tests for what happens when `tools.apply` reuses a person.

Reuse itself is right and has to stay: in a village where everyone is called
Micó, Ribera or Sarrió, two branches reach the same couple often, and a
proposal that names someone already in the tree by their `_FSFTID` should hang
off that record instead of making a second one.

What was wrong is that reuse wrote the link on one side only. `render_individual`
gives a person we *create* their `1 FAMS`; a person we reuse got nothing, so the
new family named them and they did not name it back. On 05-09-2026 that put one
Maria Torres in two branches of the Micó Bolasell tree at once -- Sant Julià de
Ramis in 1884 and Jorquera in 1760 -- and nothing said a word until Ancestris
repaired the missing FAMS on its next save and recomputed the Sosa numbers
through the link that should never have existed.

    python3 -m tools.tests.test_apply_reuse
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.apply import apply_parents
from tools.gedcom.lines import GedcomFile
from tools.gedcom.splice import Splicer

EXEMPLE = str(Path(__file__).resolve().parent / "exemple.ged")

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def _record(lines: list[str], xref: str) -> list[str]:
    head = next((n for n, l in enumerate(lines) if l.startswith(f"0 @{xref}@ ")), None)
    if head is None:
        return []
    end = next(
        (n for n, l in enumerate(lines[head + 1 :], head + 1) if l.startswith("0 ")),
        len(lines),
    )
    return lines[head:end]


def test_a_reused_person_names_the_new_family_back() -> None:
    print("\nreusing someone the tree already has")
    # @I00010@ Josep Segarra Vives is in the file with MK9P-8TR and one family,
    # @F00005@. The proposal hands him a second one as the father of @I00012@.
    entry = {
        "kind": "parents",
        "target": "I00012",
        "accept": True,
        "parents": [
            {"given": "Josep", "surname": "Segarra Vives", "sex": "M", "fsftid": "MK9P-8TR"},
            {"given": "Roser", "surname": "Caselles", "sex": "F"},
        ],
    }
    ged = GedcomFile(EXEMPLE)
    splicer = Splicer(ged)
    _, notes = apply_parents(splicer, ged, [entry])
    lines = splicer.apply()

    fam = next(
        l.split("@")[1]
        for l in reversed(lines)
        if l.startswith("0 @F") and l.endswith(" FAM")
    )
    josep = _record(lines, "I00010")
    check("1 HUSB @I00010@" in _record(lines, fam), "the new family names him")
    check(f"1 FAMS @{fam}@" in josep, "and he names the new family", str(josep))
    check("1 FAMS @F00005@" in josep, "without losing the one he had")
    check(
        sum(1 for l in josep if l.startswith("1 FAMS ")) == 2,
        "two families, not three",
        str([l for l in josep if l.startswith("1 FAMS ")]),
    )
    check(
        any(n.startswith("CHECK @I00010@") and "@F00005@" in n for n in notes),
        "and the run says out loud that he already had one",
        str(notes),
    )


def test_someone_created_this_run_and_then_reused() -> None:
    print("\nreusing someone created earlier in the same run")
    # The same person proposed as a parent of two different targets. The second
    # time round she is not in the file yet -- she is a record queued this run,
    # which `insert_into` cannot see at all.
    mother = {"given": "Roser", "surname": "Caselles", "sex": "F", "fsftid": "ZZZZ-999"}
    entries = [
        {"kind": "parents", "target": "I00012", "accept": True, "parents": [dict(mother)]},
        {"kind": "parents", "target": "I00013", "accept": True, "parents": [dict(mother)]},
    ]
    ged = GedcomFile(EXEMPLE)
    splicer = Splicer(ged)
    apply_parents(splicer, ged, entries)
    lines = splicer.apply()

    roser = [l for l in lines if "Roser" in l and l.startswith("1 NAME")]
    check(len(roser) == 1, "written once, not twice", str(len(roser)))
    made = [l.split("@")[1] for l in lines if l.startswith("0 @I") and l.endswith(" INDI")]
    new = [x for x in made if x not in ged.by_xref]
    record = _record(lines, new[-1])
    fams = [l for l in record if l.startswith("1 FAMS ")]
    check(len(fams) == 2, "she names both families", str(record))
    check(
        record.index(fams[-1]) < record.index("1 CHAN"),
        "and the second FAMS lands before CHAN, where Ancestris keeps it",
        str(record),
    )


def test_every_spouse_link_points_both_ways() -> None:
    print("\nthe rule, over the whole file this writes")
    entries = [
        {
            "kind": "parents",
            "target": "I00012",
            "accept": True,
            "parents": [
                {"given": "Josep", "surname": "Segarra Vives", "sex": "M", "fsftid": "MK9P-8TR"},
                {"given": "Rita", "surname": "Vives Alcaraz", "sex": "F", "fsftid": "KXQ2-8YT"},
            ],
        },
        {
            "kind": "parents",
            "target": "I00013",
            "accept": True,
            "parents": [
                {"given": "Tomàs", "surname": "Segarra Ferrandis", "sex": "M"},
                {"given": "Rita", "surname": "Vives Alcaraz", "sex": "F", "fsftid": "KXQ2-8YT"},
            ],
        },
    ]
    ged = GedcomFile(EXEMPLE)
    splicer = Splicer(ged)
    apply_parents(splicer, ged, entries)
    lines = splicer.apply()

    spouses: dict[str, set[str]] = {}
    fams: dict[str, set[str]] = {}
    current = None
    for line in lines:
        if line.startswith("0 @"):
            current = line.split("@")[1]
        elif current and line.startswith(("1 HUSB @", "1 WIFE @")):
            spouses.setdefault(current, set()).add(line.split("@")[1])
        elif current and line.startswith("1 FAMS @"):
            fams.setdefault(current, set()).add(line.split("@")[1])

    missing = [
        f"@{person}@ is a spouse in @{fam}@ and does not say so"
        for fam, people in spouses.items()
        for person in people
        if fam not in fams.get(person, set())
    ]
    check(not missing, "no half-linked marriage anywhere", "; ".join(missing))
    dangling = [
        f"@{person}@ claims @{fam}@, which does not name them"
        for person, claimed in fams.items()
        for fam in claimed
        if person not in spouses.get(fam, set())
    ]
    check(not dangling, "and no FAMS pointing at nobody", "; ".join(dangling))


def main() -> int:
    test_a_reused_person_names_the_new_family_back()
    test_someone_created_this_run_and_then_reused()
    test_every_spouse_link_points_both_ways()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

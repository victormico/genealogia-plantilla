"""Acceptance tests for tools.match's proposal file.

Both tests pin the same regression: tools.match --live regenerates
reports/fsftid-backfill.yaml from scratch every run, with no memory of what it
proposed last time. Without these two checks, that shows up as the same
"confident" match for someone who already has a `_FSFTID` (nothing left to
backfill), or the same candidate a human already rejected -- reappearing every
week, forever, indistinguishable from something new.

    python3 -m tools.tests.test_match
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools.match import Candidate, Match, Score, match_trees, previously_decided, write_proposals
from tools.people import Person, Tree

from tools.config import ROOT

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


MINIMAL_HEADER = "0 HEAD\n1 GEDC\n2 VERS 5.5.1\n2 FORM LINEAGE-LINKED\n1 CHAR UTF-8\n"


def _write_ged(tmp: Path, name: str, individuals: str) -> Tree:
    path = tmp / name
    path.write_text(MINIMAL_HEADER + individuals + "0 TRLR\n", encoding="utf-8")
    return Tree(path)


def test_linked_person_is_not_rescored() -> None:
    print("\nqui ja té _FSFTID no es torna a puntuar ni a proposar")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        canon = _write_ged(
            tmp,
            "canon.ged",
            "0 @I1@ INDI\n1 NAME Joan /Exemple/\n1 SEX M\n1 _FSFTID ABCD-123\n"
            "0 @I2@ INDI\n1 NAME Maria /Sala/\n1 SEX F\n",
        )
        fs = _write_ged(
            tmp,
            "fs.ged",
            "0 @F1@ INDI\n1 NAME Joan /Exemple/\n1 SEX M\n"
            "0 @F2@ INDI\n1 NAME Maria /Sala/\n1 SEX F\n",
        )
        matches = match_trees(canon, fs)
        by_xref = {m.canon.xref: m for m in matches}

        linked = by_xref["I1"]
        check(linked.bucket == "linked", "qui ja té _FSFTID queda «linked»", linked.bucket)
        check(linked.best is None, "«linked» no porta candidat associat")

        # The already-linked FS person must not be up for grabs by someone else,
        # and must not be reported as "only on FamilySearch" either -- both would
        # be wrong, since it *is* matched, just not through scoring.
        unlinked = by_xref["I2"]
        check(
            unlinked.best is None or unlinked.best.fs.xref != "F1",
            "el FamilySearch de qui ja està vinculat no queda lliure per un altre",
        )

        out = tmp / "fsftid-backfill.yaml"
        write_proposals(matches, out, reports_dir=tmp)
        written = out.read_text(encoding="utf-8")
        check(
            '"I1"' not in written,
            "qui ja està vinculat no surt al fitxer de propostes",
        )


def test_previously_decided_pair_is_not_reproposed() -> None:
    print("\nun parell (persona, fsftid) ja decidit no es torna a proposar")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "descartades").mkdir()
        (tmp / "descartades" / "fsftid-backfill.yaml").write_text(
            '- target: "I9"\n  fsftid: "ZZZZ-999"\n  confidence: review\n  accept: false\n',
            encoding="utf-8",
        )

        decided = previously_decided(tmp)
        check(
            ("I9", "ZZZZ-999") in decided,
            "previously_decided llegeix descartades/fsftid-backfill.yaml",
        )

        canon_person = Person(
            xref="I9", name="X /Y/", given="X", surname="Y", sex="M",
            birth_date=None, birth_place=None, death_date=None, death_place=None,
            fsftid=None, famc=None,
        )
        fs_person = Person(
            xref="ZZZZ-999", name="X /Y/", given="X", surname="Y", sex="M",
            birth_date=None, birth_place=None, death_date=None, death_place=None,
            fsftid="ZZZZ-999", famc=None,
        )
        rejected_again = Match(
            canon_person,
            Candidate(fs_person, Score(8.0, ["surname identical"])),
            None,
            "confident",
        )
        out = tmp / "fsftid-backfill.yaml"
        n = write_proposals([rejected_again], out, reports_dir=tmp)
        check(n == 0, "el candidat ja rebutjat no torna a sortir", f"{n} propostes")

        # A genuinely different candidate for the same person is not held back
        # by an unrelated past decision about somebody else's fsftid.
        fresh_person = Person(
            xref="ZZZZ-000", name="X /Y/", given="X", surname="Y", sex="M",
            birth_date=None, birth_place=None, death_date=None, death_place=None,
            fsftid="ZZZZ-000", famc=None,
        )
        fresh = Match(
            canon_person,
            Candidate(fresh_person, Score(8.0, ["surname identical"])),
            None,
            "confident",
        )
        n2 = write_proposals([fresh], out, reports_dir=tmp)
        check(n2 == 1, "un candidat nou i diferent sí que es proposa", f"{n2} propostes")


def main() -> int:
    test_linked_person_is_not_rescored()
    test_previously_decided_pair_is_not_reproposed()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

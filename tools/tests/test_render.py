"""Tests for rendering new records in the file's own conventions.

A wrong date or a wrong place here would not crash anything -- it would quietly
put an ancestor in the wrong century or the wrong village. So they are checked
against a real GEDCOM rather than a hand-made string.

That GEDCOM is `exemple.ged`, deliberately and not the tree from config.yaml:
these assertions are about known values, and a test that has to be edited every
time the data legitimately changes is a test that gets edited without being read.

    python3 -m tools.tests.test_render
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.gedcom.lines import GedcomFile
from tools.render import PlaceBook, render_date, render_individual, render_name

from tools.config import ROOT
EXAMPLE = ROOT / "exemple.ged"

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_dates() -> None:
    print("\ndates")
    cases = [
        ("1859-10-17", "17 OCT 1859"),
        ("1992-11-16", "16 NOV 1992"),
        ("1785-01-05", "5 JAN 1785"),
        ("1845-03", "MAR 1845"),
        ("1842", "1842"),
        ("26 DEC 1803", "26 DEC 1803"),
        (None, None),
        ("", None),
    ]
    for given, want in cases:
        got = render_date(given)
        check(got == want, f"{given!r} -> {want!r}", repr(got))

    # Spanish qualifiers from FamilySearch become proper GEDCOM ABT.
    check(render_date("APROXIMADAMENTE 1800") == "ABT 1800", "APROXIMADAMENTE -> ABT")
    check(render_date("ANTES 23 APR 1775") == "ABT 23 APR 1775", "ANTES -> ABT")


def test_names() -> None:
    print("\nnames")
    lines = render_name("Josep", "Segarra Molins")
    check(lines[0] == "1 NAME Josep /SEGARRA MOLINS/", "surname upper-cased in NAME", lines[0])
    check(lines[1] == "2 GIVN Josep", "GIVN kept as written")
    check(lines[2] == "2 SURN SEGARRA MOLINS", "SURN upper-cased")
    check(render_name("Maria", "")[0] == "1 NAME Maria", "no slashes without a surname")


def test_places() -> None:
    print("\nplaces")
    ged = GedcomFile(EXAMPLE)
    book = PlaceBook.from_gedcom(ged)
    check(len(book.by_town) >= 5, f"{len(book.by_town)} towns learned from the file")

    # A Castilian exonym must come back as the tree's own Catalan spelling,
    # complete with the coordinates already recorded for that town.
    lines = book.lookup("Fontanares, Valencia, Comunidad Valenciana, España")
    check(
        lines
        and lines[0]
        == "2 PLAC , Fontanars dels Alforins, , Província de València, "
        "Comunitat Valenciana, Espanya",
        "Fontanares -> Fontanars dels Alforins",
        lines[0] if lines else "nothing",
    )
    check("4 LATI N38.78423" in lines, "coordinates come along", str(lines))
    # Under the PLAC, not next to it: a `2 MAP` beside a `2 PLAC` is what Ancestris
    # flags as «MAP no és una GEDCOM 5.5.1 compatible aquí».
    check(lines[1] == "3 MAP", "MAP re-levelled under PLAC", str(lines))

    # Onteniente -> Ontinyent, and the doubled town name FamilySearch sometimes
    # writes must not confuse the lookup.
    lines = book.lookup("Onteniente, Onteniente, Valencia, Comunidad Valenciana, España")
    check(
        lines and "Ontinyent" in lines[0] and "Comunitat Valenciana" in lines[0],
        "Onteniente -> Ontinyent",
        lines[0] if lines else "nothing",
    )

    # The regression that mattered: an unknown town must NOT fall through to the
    # province and relocate the person to the city of the same name. Uses a
    # deliberately absent place name, so importing real places cannot make this
    # test pass by accident later.
    book2 = PlaceBook.from_gedcom(ged)
    absent = "Sant Hipòlit de Prova, Cabanes de Prova, Gerona, Cataluña, España"
    lines = book2.lookup(absent)
    check(
        lines and "Sant Hipòlit de Prova" in lines[0],
        "unknown town keeps its own name instead of falling through",
        lines[0] if lines else "nothing",
    )
    check(
        lines and "Girona, Catalunya, Espanya" in lines[0],
        "wider levels translated to the file's spellings",
        lines[0] if lines else "nothing",
    )
    check(
        lines
        and lines[0]
        == "2 PLAC Sant Hipòlit de Prova, Cabanes de Prova, , Girona, Catalunya, Espanya",
        "hamlet and municipality fill the first two slots",
        lines[0] if lines else "nothing",
    )
    check(
        not any("LATI" in line for line in lines),
        "no invented coordinates for an unknown place",
    )
    check(absent in book2.unknown, "unknown place is reported for review")

    # The city of Girona is known, so it must still resolve with coordinates --
    # the guard above must not have broken legitimate province-name towns.
    girona = book2.lookup("Gerona, Gerona, Cataluña, España")
    check(
        girona and "LATI" in " ".join(girona),
        "the city of Girona still resolves with coordinates",
        str(girona),
    )

    # A four-level FamilySearch place still maps correctly.
    plac = book2.best_effort("Jorquera, Albacete, Castilla-La Mancha, España")
    check(
        plac == ", Jorquera, , Albacete, Castella i la Manxa, Espanya",
        "four-level place maps to town slot",
        plac,
    )


def test_individual_shape() -> None:
    print("\nindividual record")
    ged = GedcomFile(EXAMPLE)
    book = PlaceBook.from_gedcom(ged)
    lines = render_individual(
        "I09999",
        given="Josep",
        surname="Segarra Molins",
        sex="M",
        birth_date="1859-10-17",
        birth_place="Fontanares, Valencia, Comunidad Valenciana, España",
        fsftid="MK9P-8TR",
        source_xrefs=["S00001"],
        object_files=["Fonts/Josep_Segarra_Molins_Bateig.pdf"],
        fams=["F00007"],
        places=book,
        change_date="26 JUL 2026",
        change_time="23:36:00",
    )
    check(lines[0] == "0 @I09999@ INDI", "starts at level 0")
    check("1 SEX M" in lines, "sex written")
    check("1 BIRT" in lines and "2 DATE 17 OCT 1859" in lines, "birth event")
    check("1 _FSFTID MK9P-8TR" in lines, "FamilySearch id recorded")
    check("1 SOUR @S00001@" in lines, "citation attached")
    check("2 FILE Fonts/Josep_Segarra_Molins_Bateig.pdf" in lines, "document linked")
    check("1 FAMS @F00007@" in lines, "family link")
    # Ancestris writes `1 CHAN / 2 DATE / 3 TIME` on every record in the file, so
    # imports have to as well or they stand out as not having come from Ancestris.
    check(lines[-3] == "1 CHAN", "CHAN block is last, as Ancestris writes it")
    check(lines[-2] == "2 DATE 26 JUL 2026", "CHAN carries the date")
    check(lines[-1] == "3 TIME 23:36:00", "CHAN carries the time at level 3")

    # Levels must never jump by more than one, or Ancestris rejects the record.
    levels = [int(line.split(" ", 1)[0]) for line in lines]
    jumps = [
        (a, b) for a, b in zip(levels, levels[1:]) if b > a + 1
    ]
    check(not jumps, "no level jumps greater than one", str(jumps))

    # Nothing must be written for a person with no dates or places at all.
    bare = render_individual("I09998", given="Pere", surname="Gres", sex="M")
    check("1 BIRT" not in bare, "no empty BIRT block")
    check(len(bare) == 5, "bare record is just name and sex", str(bare))


def main() -> int:
    if not EXAMPLE.exists():
        print(f"missing {EXAMPLE}")
        return 2
    test_dates()
    test_names()
    test_places()
    test_individual_shape()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

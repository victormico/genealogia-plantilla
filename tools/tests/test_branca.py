"""Acceptance tests for cutting a branch out of the tree.

What this file pins is the promise the portal makes to a relative: **what is not
in their branch is not in their file.** Not hidden behind a privacy flag that a
setting could turn off -- absent, with no pointer left dangling towards it.

The branch used is the one of exemple.ged's Sosa 6, Vicent SEGARRA TORRENT,
because it has every case in it: ancestors on both of his parents' sides, a
daughter (Sosa 3) whose husband comes from the other half of the tree, and
grandchildren.

    python3 -m tools.tests.test_branca
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools.branca import by_sosa, extract, render, write
from tools.config import ConfigError, example_tree
from tools.gedcom.lines import GedcomFile

CANONICAL = example_tree()

# Sosa 6 and his ancestors (12, 13, 24, 25, 48, 49), and their descendants: his
# daughter Marta (Sosa 3) and her two children, Aina (Sosa 1) and Bernat.
CORE = {"I00006", "I00010", "I00011", "I00015", "I00016", "I00017", "I00018",
        "I00003", "I00001", "I00014"}
# The spouses who married in: his wife Empar and Marta's husband Jordi.
SPOUSES = {"I00007", "I00002"}
# The other half: Jordi's ancestors. None of them may appear.
OUTSIDE = {"I00004", "I00005", "I00008", "I00009", "I00012", "I00013"}
FAMILIES = {"F00001", "F00003", "F00005", "F00007", "F00008"}

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_who_is_in(ged: GedcomFile) -> None:
    print("\nqui entra a la branca")
    b = extract(ged, "I00006")
    check(b.people == CORE | SPOUSES, "avantpassats, descendents i cònjuges",
          f"sobren {sorted(b.people - CORE - SPOUSES)}, falten {sorted(CORE | SPOUSES - b.people)}")
    check(not b.people & OUTSIDE, "cap avantpassat del cònjuge", f"{sorted(b.people & OUTSIDE)}")
    check(b.families == FAMILIES, "les famílies on algú de dins és pare, mare o fill",
          f"{sorted(b.families)}")
    check(by_sosa(ged, 6) == "I00006", "--sosa 6 és el mateix que I00006")
    check(extract(ged, "@I00006@").people == b.people, "l'xref pot portar les arroves")


def test_the_whole_tree_is_a_branch_of_the_root(ged: GedcomFile) -> None:
    print("\nla branca del Sosa 1 és l'arbre sencer")
    b = extract(ged, by_sosa(ged, 1))
    check(len(b.people) == len(ged.of_type("INDI")), "totes les persones",
          f"{len(b.people)} de {len(ged.of_type('INDI'))}")
    check(len(b.families) == len(ged.of_type("FAM")), "totes les famílies")


def test_nothing_points_outside(ged: GedcomFile) -> None:
    print("\nel fitxer no apunta enlloc de fora")
    b = extract(ged, "I00006")
    with tempfile.TemporaryDirectory() as tmp:
        out = GedcomFile(write(ged, b, Path(tmp) / "branca.ged"))
    defined = set(out.by_xref)
    cited = {ln.pointer for ln in out.lines if ln and ln.level > 0 and ln.pointer}
    check(cited <= defined, "cap punter penjant", f"{sorted(cited - defined)}")
    check(not defined & OUTSIDE, "les persones de fora no hi són")
    check({"S00001", "S00002"} <= defined, "les fonts que citen els de dins sí")
    check(not out.has_bom, "sense BOM, que el tree-import de webtrees no el vol")
    check(out.records[-1].tag == "TRLR", "acaba amb TRLR")

    jordi = {ln.tag: ln.pointer for ln in out.record_lines("I00002")[1:] if ln.pointer}
    check("FAMC" not in jordi, "el cònjuge entra sense els seus pares")
    check(jordi.get("FAMS") == "F00001", "però amb el seu matrimoni")


def test_prose_and_tags_are_kept(ged: GedcomFile) -> None:
    print("\nla resta de cada registre passa tal com és")
    b = extract(ged, "I00006")
    text = render(ged, b)
    original = ged.render()
    lost = [
        ln.raw for x in b.people for ln in ged.record_lines(x)
        if ln.tag not in {"FAMC", "FAMS"} and ln.raw not in text
    ]
    check(not lost, "cap línia de les persones de dins es perd", f"{lost[:3]}")
    check(text.count("_SOSADABOVILLE") < original.count("_SOSADABOVILLE"),
          "els números de Sosa dels de fora se'n van amb ells")


def test_a_wrong_root_says_so(ged: GedcomFile) -> None:
    print("\nuna arrel que no és cap persona")
    for root in ("I99999", "F00001"):
        try:
            extract(ged, root)
            check(False, f"{root} no és cap persona")
        except ConfigError:
            check(True, f"{root} no és cap persona")
    try:
        by_sosa(ged, 9999)
        check(False, "cap persona té el Sosa 9999")
    except ConfigError:
        check(True, "cap persona té el Sosa 9999")


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    ged = GedcomFile(CANONICAL)

    test_who_is_in(ged)
    test_the_whole_tree_is_a_branch_of_the_root(ged)
    test_nothing_points_outside(ged)
    test_prose_and_tags_are_kept(ged)
    test_a_wrong_root_says_so(ged)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

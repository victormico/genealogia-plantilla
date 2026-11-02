"""Acceptance tests for what the portal is built from.

Only the parts that need neither PHP nor a network: which trees `portal:` in
config.yaml asks for, and the files they are imported from. Installing and
serving webtrees is `python -m tools.portal local`, tried by hand.

    python3 -m tools.tests.test_portal
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools.config import ConfigError, example_tree
from tools.gedcom.lines import GedcomFile
from tools.portal import gedcoms, trees

CANONICAL = example_tree()

CONFIG = {
    "estat": {"arrel": ""},
    "portal": {
        "titol": "Família Figuerola Segarra",
        "branques": {
            "branca-segarra": {"titol": "Branca Segarra", "sosa": 6, "llengua": "es", "compte": "segarra"},
            "branca-mascarell": {"xref": "@I00009@"},
        },
    },
}

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_the_plan(ged: GedcomFile) -> None:
    print("\nquins arbres demana el config")
    plan = trees(CONFIG, ged)
    whole, segarra, mascarell = plan
    check([t.name for t in plan] == ["arbre", "branca-segarra", "branca-mascarell"],
          "l'arbre sencer primer, i després les branques en ordre")
    check(whole.root == "I00001" and not whole.branch, "el sencer s'obre al Sosa 1")
    check(whole.account == "familia" and whole.language == "ca", "compte i llengua per defecte")
    check(segarra.root == "I00006", "una branca per Sosa")
    check(segarra.account == "segarra" and segarra.language == "es", "amb el seu compte i la seua llengua")
    check(mascarell.root == "I00009" and mascarell.account == "branca-mascarell",
          "una branca per xref, i el compte pren el nom de la branca")

    bare = trees({}, ged)
    check(len(bare) == 1 and bare[0].title == "Arbre familiar", "sense `portal:`, només l'arbre sencer")
    check(trees({"estat": {"arrel": "I00002"}}, ged)[0].root == "I00002",
          "el sencer s'obre a `estat.arrel` si n'hi ha")


def test_a_bad_branch_says_so(ged: GedcomFile) -> None:
    print("\nuna branca mal escrita")
    for spec in ({"titol": "sense arrel"}, {"sosa": 9999}):
        try:
            trees({"portal": {"branques": {"b": spec}}}, ged)
            check(False, f"{spec}")
        except ConfigError:
            check(True, f"{spec} s'atura amb un missatge")


def test_the_files(ged: GedcomFile) -> None:
    print("\nels fitxers que s'importen")
    with tempfile.TemporaryDirectory() as tmp:
        files = gedcoms(Path(tmp), ged, trees(CONFIG, ged))
        whole = files["arbre"].read_text(encoding="utf-8")
        segarra = GedcomFile(files["branca-segarra"])
        check(set(files) == {"arbre", "branca-segarra", "branca-mascarell"}, "un per arbre")
        check(not whole.startswith("﻿"), "el sencer, sense BOM")
        check(whole == ged.render().lstrip("﻿"), "i sense cap altre canvi")
        check(len(segarra.of_type("INDI")) == 12, "la branca, retallada",
              f"{len(segarra.of_type('INDI'))} persones")


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    ged = GedcomFile(CANONICAL)

    test_the_plan(ged)
    test_a_bad_branch_says_so(ged)
    test_the_files(ged)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

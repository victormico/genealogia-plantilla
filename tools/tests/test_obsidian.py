"""Acceptance tests for the obsidian-charted-roots export.

The export exists to work around one thing: Charted Roots 0.22.76 writes the
raw PLAC string into YAML frontmatter unquoted, and a positional six-level PLAC
can start with a comma, which YAML rejects. So the test that matters is that no
exported PLAC starts with a comma, and that nothing *but* PLAC changed.

    python3 -m tools.tests.test_obsidian
"""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

from tools.config import tree_path
from tools.gedcom.lines import GedcomFile
from tools.obsidian import build, normalise_place, verify_form

CANONICAL = tree_path()

_PLAC = re.compile(r"^\d+ PLAC (?P<value>.*)$")
_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_normalise_place() -> None:
    print("\nnormalise_place")
    cases = [
        # The crash case: empty Aldea, real postal code.
        (
            ", Jorquera, 02041, Albacete, Castella i la Manxa, Espanya",
            "Jorquera, Albacete, Castella i la Manxa, Espanya",
        ),
        # A real Aldea survives at the front.
        (
            "El Poblet, Fontanars dels Alforins, , Província de València, Comunitat Valenciana, Espanya",
            "El Poblet, Fontanars dels Alforins, Província de València, Comunitat Valenciana, Espanya",
        ),
        # Accents and the Catalan " i " are untouched.
        (
            ", Girona, , Girona, Catalunya, Espanya",
            "Girona, Girona, Catalunya, Espanya",
        ),
    ]
    for before, want in cases:
        got = normalise_place(before)
        check(got == want, f"{before[:34]}…", f"got {got!r}")

    check(
        normalise_place(", Jorquera, 02041, Albacete, x, y", drop_postal=False)
        == "Jorquera, 02041, Albacete, x, y",
        "drop_postal=False keeps the postal code",
    )


def test_export_is_plac_only() -> None:
    print("\nexport touches PLAC and nothing else")
    ged = GedcomFile(CANONICAL)
    out, changes = build(ged)

    check(len(out) == len(ged.raw), "line count unchanged", f"{len(out)} vs {len(ged.raw)}")
    check(bool(changes), "the example tree has PLAC lines that need rewriting",
          str(len(changes)))

    changed_indices = {lineno - 1 for lineno, _, _ in changes}
    non_plac = [i for i in changed_indices if not _PLAC.match(ged.raw[i])]
    check(not non_plac, "every changed line is a PLAC line", f"{non_plac[:5]}")

    untouched = [i for i in range(len(out)) if i not in changed_indices and out[i] != ged.raw[i]]
    check(not untouched, "unchanged lines are byte-identical", f"{untouched[:5]}")


def test_no_yaml_hostile_values() -> None:
    print("\nno PLAC value can break YAML")
    ged = GedcomFile(CANONICAL)
    out, _ = build(ged)

    values = [m.group("value") for raw in out if (m := _PLAC.match(raw))]
    check(bool(values), "export still has PLAC lines", f"{len(values)}")

    # YAML plain scalars cannot start with a flow indicator, which is what an
    # unquoted `spouse1_marriage_location:` trips over.
    flow = [v for v in values if v[:1] in ",[]{}&*!|>%@`\"'#"]
    check(not flow, "no PLAC starts with a YAML indicator", f"{flow[:3]}")

    empty_slots = [v for v in values if v.strip() and ", ," in v]
    check(not empty_slots, "no empty slots left mid-chain", f"{empty_slots[:3]}")

    postal = [v for v in values if re.search(r"\b\d{5}\b", v)]
    check(not postal, "no postal code left to become a place", f"{postal[:3]}")


def test_form_guard() -> None:
    print("\nheader FORM guard")
    ged = GedcomFile(CANONICAL)
    try:
        verify_form(ged)
        check(True, "canonical FORM accepted")
    except ValueError as exc:
        check(False, "canonical FORM accepted", str(exc))

    # A changed FORM must stop the export rather than shift place levels blindly.
    ged.lines = [
        replace(ln, value="Ciutat, Codi Postal, País")
        if ln and ln.tag == "FORM" and "Codi Postal" in ln.value
        else ln
        for ln in ged.lines
    ]
    try:
        verify_form(ged)
        check(False, "a changed FORM is refused")
    except ValueError:
        check(True, "a changed FORM is refused")


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    test_normalise_place()
    test_export_is_plac_only()
    test_no_yaml_hostile_values()
    test_form_guard()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

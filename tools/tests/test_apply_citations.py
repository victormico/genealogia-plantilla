"""Offline tests for importing FamilySearch citations into the GEDCOM.

The point of carrying citations through the proposal is that they land in the
tree as real SOUR records -- the parish register with its ARK -- instead of
every imported ancestor being hung on the generic «FamilySearch Family Tree».
These run against `exemple.ged` so they assert on the writing, not on anybody's
real family.

    python3 -m tools.tests.test_apply_citations
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.apply import _citation_specs, _link_citations, apply_parents
from tools.gedcom.lines import GedcomFile
from tools.gedcom.splice import Splicer

# Resolved next to this file, and not as a path relative to the working
# directory: that only exists when the run starts in the package's own
# checkout. The family repositories pip-install these tools and run the suite
# from their own root, where no such directory is there -- which is exactly
# where this first broke.
EXEMPLE = str(Path(__file__).resolve().parent / "exemple.ged")

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


ARK = "https://www.familysearch.org/ark:/61903/1:1:XVQ4-8QN"
BAPTISM = {
    "title": 'Antonio Baliente, "España, Diócesis de Albacete, registros parroquiales, 1504-1979"',
    "collection": "España, Diócesis de Albacete, registros parroquiales, 1504-1979",
    "text": "…, Entry for Antonio Baliente and Juan Baliente, 22 Apr 1786.",
    "url": ARK,
    "names": ["Antonio Baliente", "Juan Baliente"],
    "shared_with_target": True,
}
BURIAL = {"title": 'Juan Valiente, "España, defunciones, 1600-1920"', "url": "ark:/1807"}


def _proposal() -> dict:
    return {
        "kind": "parents",
        "target": "I00012",
        "accept": True,
        "parents": [
            {"given": "Juan", "surname": "Gomez", "sex": "M", "fsftid": "LB8Z-YC4",
             "citations": [BAPTISM, BURIAL]},
            # The same baptism, reached through the mother. One document.
            {"given": "Ana", "surname": "Martinez", "sex": "F", "fsftid": "9D4L-CSW",
             "citations": [dict(BAPTISM)]},
        ],
    }


def test_specs_drop_what_cannot_be_a_source() -> None:
    print("\nreading citations off a proposal")
    block = {
        "citations": [
            BAPTISM,
            {"collection": "sense títol propi"},   # falls back to the collection
            {"url": "https://example.invalid/x"},  # nothing to key a SOUR on
            {"title": "   "},                      # blank is not a title
            "no soc un dict",
        ]
    }
    specs = _citation_specs(block)
    check(len(specs) == 2, "two usable, three dropped", str(len(specs)))
    check(specs[0]["url"] == ARK, "the ARK is carried through", specs[0].get("url", ""))
    check(specs[1]["title"] == "sense títol propi", "collection stands in for a title")
    # An untitled SOUR would be keyed by "" and silently swallow the next one.
    check(all(s["title"].strip() for s in specs), "no spec goes out untitled")


def test_only_shared_documents_are_evidence_for_the_link() -> None:
    print("\nwhich citations belong on the family record")
    entry = _proposal()
    entry["parents"][0]["citations"] = [BAPTISM, BURIAL]
    shared = _link_citations(entry)
    check(all(s["url"] == ARK for s in shared), "the burial is not evidence of a parentage")
    check(len(shared) == 2, "reached once per parent, deduped later by title", str(len(shared)))


def test_citations_reach_the_gedcom() -> None:
    print("\nwhat gets written")
    ged = GedcomFile(EXEMPLE)
    splicer = Splicer(ged)
    apply_parents(splicer, ged, [_proposal()])
    lines = splicer.apply()

    sources = [l for l in lines if l.startswith("0 @S") and l.endswith("SOUR")]
    titles = [l for l in lines if l.startswith("1 TITL ")]
    check(
        any("Diócesis de Albacete" in t for t in titles),
        "the parish register became a SOUR record of its own",
    )
    check(f"1 PUBL {ARK}" in lines, "with its ARK, so the record can be reopened")
    check(
        sum(1 for t in titles if "Diócesis de Albacete" in t) == 1,
        "cited by both parents, written once",
        str([t for t in titles if "Diócesis de Albacete" in t]),
    )
    check(len(sources) >= 3, "tree source, baptism and burial", str(len(sources)))

    # The family record asserts the parentage, so the document that names child
    # and parent together belongs on it -- once, not once per parent.
    fam_sources = [l for l in _record(lines, "FAM") if l.startswith("1 SOUR ")]
    check(len(fam_sources) == len(set(fam_sources)), "no repeated SOUR pointer", str(fam_sources))
    check(len(fam_sources) == 2, "the tree source and the shared baptism", str(fam_sources))


def test_a_proposal_without_citations_still_imports() -> None:
    print("\nthe old shape of proposal keeps working")
    entry = _proposal()
    for parent in entry["parents"]:
        parent.pop("citations")
    ged = GedcomFile(EXEMPLE)
    splicer = Splicer(ged)
    apply_parents(splicer, ged, [entry])
    lines = splicer.apply()
    check(any(l.startswith("0 @F") and l.endswith("FAM") for l in lines), "family written")
    check(
        any("FamilySearch Family Tree" in l for l in lines),
        "and still cited to the tree, as before",
    )


def _record(lines: list[str], tag: str) -> list[str]:
    """The last record of this type: everything from its `0 @X@ TAG` to the next `0 `."""
    starts = [n for n, l in enumerate(lines) if l.startswith("0 @") and l.endswith(f" {tag}")]
    if not starts:
        return []
    head = starts[-1]
    end = next((n for n, l in enumerate(lines[head + 1 :], head + 1) if l.startswith("0 ")), len(lines))
    return lines[head:end]


def main() -> int:
    test_specs_drop_what_cannot_be_a_source()
    test_only_shared_documents_are_evidence_for_the_link()
    test_citations_reach_the_gedcom()
    test_a_proposal_without_citations_still_imports()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

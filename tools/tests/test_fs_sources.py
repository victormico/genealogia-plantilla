"""Offline tests for reading the documents FamilySearch cites for a person.

`Api.citations` runs unattended inside the nightly research cron, against a
GEDCOM X payload whose fields are mostly optional and which offers three
different places to put the ARK. So the thing worth pinning is not the happy
path -- it is that every shape short of the happy path still comes back with
something, and that none of them raise.

The fixtures below are the real citation wording of the Jorquera records that
settled issue #70 of the family tree: the 1786 baptism that names Antonio
Baliente and his father Juan in the same line, and the 1754 one that names Juan
and *his* father Gil. That is the case this code exists to surface.

    python3 -m tools.tests.test_fs_sources
"""

from __future__ import annotations

import sys

from tools.fs.api import _citations, citation_key

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


# The real ARKs of the 1786 baptism, read off the live API on 30-08-2026. Two
# different ones, and the difference is the whole point: `about` is the ARK of
# THIS PERSON's entry in the record, so the son and the father each have their
# own, while the ARK quoted inside the citation is the document and is the same
# string for both.
DOCUMENT = "ark:/61903/1:1:NSB1-J6P"
SON_ENTRY = "https://www.familysearch.org/ark:/61903/1:1:NSB1-J6X"
FATHER_ENTRY = "https://www.familysearch.org/ark:/61903/1:1:NSB1-J6D"

CITATION_1786 = (
    '"España, Diócesis de Albacete, registros parroquiales, 1504-1979", '
    "<i>FamilySearch</i> (https://www.familysearch.org/ark:/61903/1:1:NSB1-J6P : "
    "Sat Aug 31 07:56:01 UTC 2024), Entry for Antonio Baliente and Juan "
    "Baliente, 22 Apr 1786."
)

BAPTISM_1786 = {
    "id": "SD-1786",
    "about": FATHER_ENTRY,
    "titles": [
        {"value": 'Antonio Baliente, "España, Diócesis de Albacete, registros parroquiales, 1504-1979"'}
    ],
    "citations": [{"value": CITATION_1786}],
    # FamilySearch really does send this, and it is the collection, not the
    # record: nothing here may mistake it for the document's ARK.
    "identifiers": {
        "http://gedcomx.org/Collection": [
            "https://www.familysearch.org/platform/records/collections/1431011"
        ]
    },
    "links": {"description": {"href": "https://api.familysearch.org/platform/sources/descriptions/WDYR-2DY?flag=fsh"}},
    "resourceType": "FSREADONLY",
}

ARK = FATHER_ENTRY

FULL = {
    "sourceDescriptions": [
        BAPTISM_1786,
        {
            "id": "SD-1807",
            "about": "https://familysearch.org/ark:/61903/1:1:FNMW-XQ9",
            "titles": [{"value": 'Juan Valiente, "España, defunciones, 1600-1920"'}],
            "citations": [
                {
                    "value": '"España, defunciones, 1600-1920", FamilySearch '
                    "(https://familysearch.org/ark:/61903/1:1:FNMW-XQ9 : "
                    "Mon Mar 10 17:12:05 UTC 2025), Entry for Juan Valiente and "
                    "Ana Martinez, 30 Nov 1807."
                }
            ],
        },
        # Rides along in the same payload but is not attached to anybody: the
        # collection the records belong to. It must not become a citation.
        {
            "id": "SD-COLLECTION",
            "titles": [{"value": "España, Diócesis de Albacete, registros parroquiales"}],
        },
    ],
    "persons": [
        {
            "id": "LB8Z-YC4",
            "sources": [
                {"description": "#SD-1786", "tags": [{"resource": "http://gedcomx.org/Birth"}]},
                {
                    "descriptionId": "SD-1807",
                    "tags": [
                        {"resource": "http://gedcomx.org/Death"},
                        {"resource": "http://gedcomx.org/Couple"},
                    ],
                },
            ],
        }
    ],
}


def test_reads_a_normal_response() -> None:
    print("\na person with two attached documents")
    cites = _citations(FULL)
    check(len(cites) == 2, "only the attached ones, not the collection", str(len(cites)))

    first = cites[0]
    check(first["url"] == ARK, "ARK read off `about`", first.get("url", ""))
    check(
        first["collection"] == "España, Diócesis de Albacete, registros parroquiales, 1504-1979",
        "collection pulled out of the quotes",
        first.get("collection", ""),
    )
    check(
        first["names"] == ["Antonio Baliente", "Juan Baliente"],
        "both people the citation names",
        str(first.get("names")),
    )
    check(first["about"] == ["naixement"], "attached as a birth", str(first.get("about")))

    second = cites[1]
    check(
        second["url"] == "https://www.familysearch.org/ark:/61903/1:1:FNMW-XQ9",
        "bare familysearch.org normalised to www, so ARKs compare equal",
        second.get("url", ""),
    )
    check(second["names"] == ["Juan Valiente", "Ana Martinez"], "the couple named", str(second.get("names")))
    check(second["about"] == ["defunció", "parella"], "both tags kept", str(second.get("about")))


def test_the_document_is_not_the_persons_entry_in_it() -> None:
    print("\nthe distinction this all rests on")
    # Written against the spec, this code keyed documents by `about` -- and the
    # live API then said the son G3CB-9ZT and the father LB8Z-YC4 shared exactly
    # ZERO ARKs while sharing five documents, because `about` is per person.
    # The rule was dead code and no offline fixture had noticed.
    cite = _citations(FULL)[0]
    check(cite["url"] == FATHER_ENTRY, "url is this person's entry", cite.get("url", ""))
    check(cite["document"] == DOCUMENT, "document is the record itself", cite.get("document", ""))
    check(cite["url"] != cite["document"], "and they are not the same string")
    check(citation_key(cite) == DOCUMENT, "the key is the document", citation_key(cite))


def test_shared_document_is_findable_though_the_entries_differ() -> None:
    print("\nthe signal the proposals actually use")
    # The 1786 baptism hangs on the son and on the father alike, each under his
    # own entry ARK. Keyed by the document, they meet; keyed by `about`, never.
    son = _citations({
        "sourceDescriptions": [dict(BAPTISM_1786, about=SON_ENTRY)],
        "persons": [{"id": "G3CB-9ZT", "sources": [{"description": "#SD-1786"}]}],
    })
    father = _citations(FULL)
    check(
        {c["url"] for c in son}.isdisjoint({c["url"] for c in father}),
        "the two entry ARKs have nothing in common -- the old key found nothing",
    )
    shared = {citation_key(c) for c in son} & {citation_key(c) for c in father}
    check(shared == {DOCUMENT}, "keyed by the document, the baptism is common", str(shared))


def test_the_collection_url_is_never_taken_for_the_document() -> None:
    print("\nidentifiers carry the collection, not the record")
    cite = _citations(FULL)[0]
    check("collections/1431011" not in citation_key(cite), "collection kept out of the key")
    check(
        "collections/1431011" not in cite.get("url", ""),
        "and out of the url",
        cite.get("url", ""),
    )


def test_survives_every_degraded_shape() -> None:
    print("\npayloads that must not raise")
    cases = {
        "None (403, or no sources)": None,
        "not a dict": [],
        "empty": {},
        "descriptions but no persons": {"sourceDescriptions": [BAPTISM_1786]},
        "person points at a description that is not there": {
            "sourceDescriptions": [BAPTISM_1786],
            "persons": [{"sources": [{"description": "#SD-NOPE"}]}],
        },
        "null members": {"sourceDescriptions": [None, {}], "persons": [None]},
        "untitled, uncited": {
            "sourceDescriptions": [{"id": "X", "about": ARK}],
            "persons": [{"sources": [{"descriptionId": "X"}]}],
        },
    }
    for label, payload in cases.items():
        try:
            got = _citations(payload)
            check(isinstance(got, list), f"{label} -> a list", repr(got))
        except Exception as exc:  # noqa: BLE001 -- the whole point is that it cannot
            check(False, f"{label} -> a list", f"{type(exc).__name__}: {exc}")

    # "descriptions but no persons" is the one degraded case that must still
    # yield something: it is a response we can read, just not one that says
    # which fact each document was attached to.
    fallback = _citations({"sourceDescriptions": [BAPTISM_1786]})
    check(len(fallback) == 1, "falls back to the descriptions themselves", str(len(fallback)))
    check("about" not in fallback[0], "with no fact tags to report", str(fallback[0].get("about")))


def test_finds_the_ark_wherever_it_is() -> None:
    print("\nthe three places an ARK can hide")
    def one(desc: dict) -> str:
        got = _citations({"sourceDescriptions": [dict(desc, id="X")],
                          "persons": [{"sources": [{"descriptionId": "X"}]}]})
        return got[0].get("url", "") if got else ""

    check(one({"about": ARK}) == ARK, "about")
    check(
        one({"identifiers": {"http://gedcomx.org/Persistent": [ARK]}}) == ARK,
        "identifiers, as a list",
    )
    check(one({"identifiers": {"http://gedcomx.org/Persistent": ARK}}) == ARK,
          "identifiers, as a bare string")
    check(one({"links": {"self": {"href": ARK}}}) == ARK, "links.self.href")
    check(one({"about": "https://www.familysearch.org/tree/person/details/LB8Z-YC4"}) == "",
          "a tree link is not a record ARK")


def test_odd_citation_wordings() -> None:
    print("\ncitation sentences that are not the usual one")
    def names(citation: str) -> list[str]:
        got = _citations({"sourceDescriptions": [{"id": "X", "citations": [{"value": citation}]}]})
        return got[0].get("names", []) if got else []

    check(
        names('"Spain, Baptisms, 1502-1940", Antonio Valiente in entry for Ana Maria '
              "Fernanda Valiente, 1809.") == ["Ana Maria Fernanda Valiente"],
        "«X in entry for Y» keeps Y",
    )
    check(
        names('"España, registros parroquiales", FamilySearch (… : …), Entry for Josefa '
              "Montero and Antonio Valiente, 13 de octubre de 1854.")
        == ["Josefa Montero", "Antonio Valiente"],
        "a Spanish date still closes the name list",
    )
    check(names("a citation phrased some other way entirely") == [],
          "no guess when the wording is unfamiliar")


def main() -> int:
    test_reads_a_normal_response()
    test_the_document_is_not_the_persons_entry_in_it()
    test_shared_document_is_findable_though_the_entries_differ()
    test_the_collection_url_is_never_taken_for_the_document()
    test_survives_every_degraded_shape()
    test_finds_the_ark_wherever_it_is()
    test_odd_citation_wordings()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

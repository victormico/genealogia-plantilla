"""Tests for the diocesan catalogue tools. No network: the session is faked.

These guard the failures that are *silent* -- the ones that return a plausible
wrong answer instead of an error:

  * the page-number padding. `_7_` and `_0100_` both answer 403, and so does the
    end of the book, so getting the padding wrong looks exactly like "this book
    is not digitised".
  * `bucket: false`. The fiche exists either way, so a tool that does not check
    this will happily hand you image URLs for a book that has no images.
  * the fixtures below are trimmed real responses, captured 30-07-2026. If the
    archive changes its field names, these stop matching and that is the point.

Run with pytest if it is installed; otherwise
`python3 -m tools.tests.test_adg` executes the same assertions.
"""

from __future__ import annotations

from ..adg import catalog, images

# -- fixtures: real responses, trimmed --------------------------------------------

FICHE_READABLE = {
    "udoc": {
        "_idudocsimple": "14233", "_idserie": "100",
        "titol": "Certificats de Matrimoni de la parròquia de Sant Cebrià de Vilafant",
        "codi": "CAT ADG 3/385 1 3 6",
        "condicions_acces": "Consulta digital al web",
        "any_inici": "1875", "any_fi": "1888",
        "llengua_i_escriptures": "Castellà",
        "fons": "Vilafant, parròquia de Sant Cebrià",
        "grup": "Matrimonis", "serie": "Còpies, extractes i certificats [Parròq]",
        "idamazon": 14233, "bucket": True,
    }
}

FICHE_ONSITE = {
    "udoc": {
        "_idudocsimple": "36697", "titol": "Certificats de Matrimoni",
        "condicions_acces": "Consulta física a la sala",
        "any_inici": "1889", "any_fi": "1952",
        "idamazon": 36697, "bucket": False,
    }
}

FICHE_CLOSED = {
    "udoc": {
        "_idudocsimple": "7511", "titol": "Lligall de documents de sagraments",
        "condicions_acces": "Fora de consulta",
        "any_inici": "1875", "any_fi": "1952",
        "idamazon": 7511, "bucket": True,
    }
}

# The parish list's `fills` says [31] while tree.php?id=25 returns four children,
# and 31 is a different parish. Kept here so the test can state it.
PARISH_ADRI = {
    "id": "25", "titol": "Adri, parròquia de Sant Llorenç", "udocs": True,
    "descripcio": "Sant Llorenç d'Adri. Arxiu parroquial conservat: Baptismes…",
    "esta_indexat": True, "fills": [31],
    "path": [["2", "ARXIU DIOCESÀ DE GIRONA"], ["24", "ARXIUS PARROQUIALS"]],
}


class FakeSession:
    """Answers from a dict of canned responses, and counts what was asked."""

    def __init__(self, json_by_path=None, existing_pages=frozenset()):
        self.json_by_path = dict(json_by_path or {})
        self.existing_pages = set(existing_pages)
        self.asked: list[str] = []
        self.heads: list[str] = []
        self.dry_run = False

    def get_json(self, path, why="", refresh=False):
        self.asked.append(path)
        return self.json_by_path.get(path)

    def image_exists(self, url, refresh=False):
        self.heads.append(url)
        return url in self.existing_pages

    def stats(self):
        return "fake"


# -- the page number, which is the whole trap ------------------------------------

def test_page_segment_pads_to_two_then_grows():
    # Verified against the live bucket: `_7_` is 403, `_07_` is 200,
    # `_100_` is 200 and `_0100_` is 403.
    assert images.page_segment(1) == "01"
    assert images.page_segment(7) == "07"
    assert images.page_segment(80) == "80"
    assert images.page_segment(99) == "99"
    assert images.page_segment(100) == "100"
    assert images.page_segment(198) == "198"


def test_page_segment_refuses_page_zero():
    try:
        images.page_segment(0)
    except ValueError as exc:
        assert "comencen a 1" in str(exc)
    else:
        raise AssertionError("la pàgina 0 no existeix i ha de petar")


def test_image_url_shape():
    url = images.image_url(14233, 7)
    assert url == ("https://arxiu-diocesa.s3.eu-west-3.amazonaws.com/"
                   "14233/14233_07_m.jpg")
    assert images.image_url(14233, 7, images.HIGH).endswith("_07_h.jpg")


def test_image_url_rejects_unknown_resolution():
    try:
        images.image_url(14233, 1, "xl")
    except ValueError as exc:
        assert "resolució" in str(exc)
    else:
        raise AssertionError("una resolució inventada ha de petar")


# -- finding the end of a book ---------------------------------------------------

def _pages(book, upto, resolution=images.MEDIUM):
    return {images.image_url(book, p, resolution) for p in range(1, upto + 1)}


def test_bisect_finds_the_last_page():
    for length in (1, 2, 7, 80, 99, 100, 198, 201):
        session = FakeSession(existing_pages=_pages(14233, length))
        found = images.bisect_last_page(session, 14233)
        assert found == length, f"llibre de {length} pàgines: ha dit {found}"


def test_bisect_is_cheap():
    # ~2*log2(n) HEADs. A book of 198 pages must not cost 198 requests.
    session = FakeSession(existing_pages=_pages(14233, 198))
    images.bisect_last_page(session, 14233)
    assert len(session.heads) < 30, f"{len(session.heads)} peticions és massa"


def test_bisect_returns_none_when_page_one_is_missing():
    # Which means "not digitised, or wrong id" -- not "zero pages".
    session = FakeSession(existing_pages=set())
    assert images.bisect_last_page(session, 99999) is None


# -- the fiche, and the field that decides ---------------------------------------

def test_readable_book_is_readable():
    book = catalog.parse_fiche(FICHE_READABLE)
    assert book.id == "14233"
    assert book.digitised
    assert book.access_kind == "open"
    assert book.readable
    assert book.why_not() == ""
    assert book.years == "1875-1888"
    assert book.s3_id == "14233"


def test_not_digitised_and_onsite_is_a_trip_not_a_bug():
    book = catalog.parse_fiche(FICHE_ONSITE)
    assert not book.digitised
    assert book.access_kind == "onsite"
    assert not book.readable
    assert "en persona" in book.why_not()


def test_digitised_but_withheld_is_still_not_readable():
    # `bucket: true` alone is not enough: this one is digitised and closed.
    book = catalog.parse_fiche(FICHE_CLOSED)
    assert book.digitised
    assert book.access_kind == "closed"
    assert not book.readable
    assert "fora de consulta" in book.why_not()


def test_fiche_id_is_not_the_series_id():
    # `_idserie: 100` is in the fixture; the book id must not pick it up, and
    # passing 100 to udocs.php returns an empty list rather than an error.
    book = catalog.parse_fiche(FICHE_READABLE)
    assert book.id == "14233"


def test_covers_years():
    book = catalog.parse_fiche(FICHE_READABLE)
    assert book.covers(1885)
    assert book.covers(1875)
    assert book.covers(1888)
    assert not book.covers(1889)
    assert not book.covers(1874)
    assert not book.covers(None)


# -- the tree --------------------------------------------------------------------

def test_children_are_asked_for_and_fills_is_never_read():
    # Adri reports `fills: [31]`, but 31 is Anglès. The only correct source of
    # children is the call, so make sure that is what happens.
    session = FakeSession({
        "tree.php?id=25": [
            {"id": "1134", "titol": "SAGRAMENTS", "udocs": True},
            {"id": "2197", "titol": "LLIBRES NOTARIALS", "udocs": True},
        ],
    })
    kids = catalog.children(session, 25)
    assert [k.id for k in kids] == ["1134", "2197"]
    assert session.asked == ["tree.php?id=25"]
    assert "31" not in [k.id for k in kids]


def test_find_parish_ignores_accents_and_case():
    session = FakeSession({
        "tree.php?parroquies=true": [
            PARISH_ADRI,
            {"id": "500", "titol": "Vilafant, parròquia de Sant Cebrià", "udocs": True},
        ],
    })
    assert [p.id for p in catalog.find_parish(session, "VILAFANT")] == ["500"]
    # The dedication is in the title, so a bare town name still has to match.
    assert [p.id for p in catalog.find_parish(session, "adri")] == ["25"]
    assert catalog.find_parish(session, "") == []


def test_documents_parses_the_slim_listing():
    session = FakeSession({
        "udocs.php?id=1203193&items=200&page=1": {
            "udocs": [{"id": "14233", "titol": "Certificats de Matrimoni (1875-1888)",
                       "codi": "CAT ADG 3/385 1 3 6", "ref": "M Certif."}],
            "items": 1,
        },
    })
    docs = catalog.documents(session, 1203193)
    assert len(docs) == 1 and docs[0].id == "14233"


def test_empty_series_is_empty_not_an_error():
    # This is what passing an `_idserie` instead of a tree id looks like.
    session = FakeSession({"udocs.php?id=100&items=200&page=1": {"udocs": [], "items": 0}})
    assert catalog.documents(session, 100) == []


def test_walk_series_respects_the_depth_limit():
    session = FakeSession({
        "tree.php?id=500": [{"id": "1565", "titol": "SAGRAMENTS", "udocs": True}],
        "tree.php?id=1565": [{"id": "13806", "titol": "Matrimonis", "udocs": True}],
        "tree.php?id=13806": [{"id": "1203193", "titol": "Còpies i certificats",
                               "udocs": True}],
    })
    found = catalog.walk_series(session, 500, depth=2)
    assert [n.id for n in found] == ["1565", "13806"]
    assert "tree.php?id=13806" not in session.asked


# -- the download cap ------------------------------------------------------------

def test_parse_pages():
    assert images.parse_pages("73") == [73]
    assert images.parse_pages("3-7") == [3, 4, 5, 6, 7]
    assert images.parse_pages("3,9,11-13") == [3, 9, 11, 12, 13]
    assert images.parse_pages("5,5,5") == [5]


def test_parse_pages_rejects_backwards_range():
    try:
        images.parse_pages("9-3")
    except ValueError as exc:
        assert "enrere" in str(exc)
    else:
        raise AssertionError("un rang cap enrere ha de petar")


def test_download_refuses_a_whole_book(tmp_path=None):
    import tempfile
    from pathlib import Path

    session = FakeSession()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            images.download_pages(session, 14233, list(range(1, 81)), Path(tmp))
        except ValueError as exc:
            assert "ús personal" in str(exc)
        else:
            raise AssertionError("80 pàgines de cop s'ha de negar")


if __name__ == "__main__":
    ran = failed = 0
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            ran += 1
            try:
                fn()
                print(f"  ok    {name}")
            except Exception as exc:  # noqa: BLE001 - a test runner reports everything
                failed += 1
                print(f"  FALLA {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran} proves, {failed} falla(des)")
    raise SystemExit(1 if failed else 0)

"""Tests for the diocesan index tools.

Two of these guard against failures that would be *silent*, which is why they
exist at all:

  * latin-1 encoding. Get it wrong and every accented surname matches nothing,
    which looks exactly like "this ancestor is not in the index".
  * the daily quota. A cap that resets when the process restarts is not a cap,
    so the counter is tested across a fresh object.

Run with pytest if it is installed; otherwise `python3 -m tools.tests.test_apv`
executes the same assertions.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..apv import coverage
from ..apv.parse import parse_fiche, parse_results, to_markdown
from ..apv.query import BAPTISM, encode, url
from ..apv.session import Quota


# -- encoding ------------------------------------------------------------------

def test_encode_lowercases_and_trims():
    assert encode("  SEGARRA  ") == "segarra"


def test_url_has_every_field_and_page_one():
    built = url(surname="Segarra", event_place="ontinyent")
    assert built.startswith("https://www.arxparrvalencia.org/llistats_genealogia_nou1.php?")
    assert "a1=segarra" in built
    assert "llocevento=ontinyent" in built
    # every form field present, blank ones included
    for field in ("nom", "a2", "a2op", "labuamat", "lconyuge", "cognomcj", "nomcon"):
        assert f"{field}=" in built


def test_url_rejects_unknown_field():
    try:
        url(nonexistent="x")
    except ValueError as exc:
        assert "no té" in str(exc)
    else:
        raise AssertionError("una clau desconeguda ha de petar, no passar en silenci")


# -- coverage ------------------------------------------------------------------

def test_ontinyent_baptism_gaps_are_respected():
    # 1747 falls in the 1744-1755 hole, which is where a whole generation of the
    # original tree got stuck: the baptism simply is not in the index.
    assert not coverage.covers("ontinyent", coverage.BAPTISM, 1747)
    assert coverage.covers("ontinyent", coverage.BAPTISM, 1621)
    assert coverage.covers("ontinyent", coverage.BAPTISM, 1715)
    assert not coverage.covers("ontinyent", coverage.BAPTISM, 1595)


def test_ontinyent_marriages_are_complete_1560_1900():
    for year in (1560, 1620, 1644, 1767, 1900):
        assert coverage.covers("ontinyent", coverage.MARRIAGE, year), year
    assert not coverage.covers("ontinyent", coverage.MARRIAGE, 1534)


def test_no_year_is_not_a_yes():
    verdict = coverage.covers("ontinyent", coverage.MARRIAGE, None)
    assert not verdict
    assert "sense any" in verdict.why


def test_embargo_blocks_recent_records():
    assert not coverage.covers("fontanars", coverage.BAPTISM, 1990)


def test_alternatives_points_at_the_marriage():
    # The whole strategy for this branch: baptism missing, marriage available.
    assert coverage.MARRIAGE in coverage.alternatives("ontinyent", 1747)
    assert coverage.BAPTISM not in coverage.alternatives("ontinyent", 1747)


# -- quota ---------------------------------------------------------------------

def _quota_in_tmp(tmp: Path, limit: int = 15) -> Quota:
    return Quota(path=tmp / "apv-quota.json", limit=limit)


def test_quota_counts_and_refuses():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        q = _quota_in_tmp(tmp, limit=3)
        for n in range(3):
            q.check()
            q.spend(f"consulta {n}")
        assert q.remaining() == 0
        try:
            q.check()
        except RuntimeError as exc:
            assert "gastades" in str(exc)
        else:
            raise AssertionError("passat el sostre s'ha de negar")


def test_quota_survives_a_restart():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        first = _quota_in_tmp(tmp)
        first.spend("una")
        first.spend("dues")
        # A brand new object, as if the process had been restarted.
        second = _quota_in_tmp(tmp)
        assert second.used == 2, "el comptador s'ha de llegir del disc"
        assert second.remaining() == 13


def test_server_count_wins():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        q = _quota_in_tmp(tmp)
        q.spend("una")
        page = ("Debido a los expolios ... limitar el acceso a las consultas a un "
                "máximo de <b>15</b> diarias, de las cuales ya has realizado <b>9</b>, "
                "por lo que tienes 6 consultas disponibles")
        assert q.reconcile(page) == 9
        assert q.used == 9, "si l'arxiu diu 9, en portem 9"


def test_reconcile_never_lowers_our_count():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        q = _quota_in_tmp(tmp)
        for n in range(5):
            q.spend(str(n))
        q.reconcile("ya has realizado 2 consultas")
        assert q.used == 5, "no es baixa el comptador propi"


# -- fiche parsing -------------------------------------------------------------

FICHE = """
<table>
<tr><th>Sagrament</th><th>Identificador</th><th>Llibre</th><th>Foli</th><th>Apunt</th><th>Sexe</th></tr>
<tr><td>1</td><td>1985133</td><td>LB 1892-1902</td><td>127v</td><td>035</td><td>H</td></tr>
<tr><td></td><td>Nom</td><td>Cognom 1</td><td>Cognom 2</td><td>Lloc Naixement</td></tr>
<tr><td>Interessat/da</td><td>Tomàs</td><td>Segarra</td><td>Bellver</td><td>Fontanars dels Alforins</td></tr>
<tr><td>Pare</td><td>Vicent</td><td>Segarra</td><td>Molins</td><td>Fontanars dels Alforins</td></tr>
<tr><td>Mare</td><td>Rita</td><td>Bellver</td><td>Ripoll</td><td>Fontanars dels Alforins</td></tr>
<tr><td>Data Naixement</td><td>13 - 08 - 1900</td><td>Data Sagrament</td><td>14 - 08 - 1900</td></tr>
<tr><td>Oficiant</td><td>Ripoll, Antonio - Coadjutor</td></tr>
</table>
"""


def test_parse_fiche_reads_kin_and_reference():
    f = parse_fiche(FICHE)
    assert f.get("identificador") == "1985133"
    assert f.get("book") == "LB 1892-1902"
    assert f.get("folio") == "127v"
    assert f.sacrament_name() == "Bateig"
    person = f.person()
    assert person is not None
    assert person.full() == "Tomàs Segarra Bellver"
    roles = {k.role for k in f.kin}
    assert {"Interessat/da", "Pare", "Mare"} <= roles
    assert f.get("birth_date") == "13 - 08 - 1900"
    assert f.get("officiant").startswith("Ripoll, Antonio")


def test_parse_fiche_keeps_accents():
    f = parse_fiche(FICHE)
    father = next(k for k in f.kin if k.role == "Pare")
    assert father.given == "Vicent"
    assert father.surname1 == "Segarra"


def test_markdown_names_the_index_not_the_manuscript():
    md = to_markdown(parse_fiche(FICHE), "Tomàs Segarra Bellver")
    assert "Tomàs Segarra Bellver" in md
    assert "no del manuscrit original" in md
    assert "| Interessat/da | Tomàs Segarra Bellver |" in md.replace("  ", " ")
    assert "no són prova" in md          # the grandparent-place warning survives


def test_parse_results_finds_book_references():
    page = """<tr><td>Inscrito/a en el</td><td>M-24 (1894_1896) Folio 4 Pda.</td>
              <td>Registro num. 33314628</td></tr>"""
    hits = parse_results(page)
    assert len(hits) == 1
    assert hits[0]["book"] == "M-24"
    assert hits[0]["from"] == "1894" and hits[0]["to"] == "1896"
    assert hits[0]["folio"] == "4"


def test_empty_page_yields_nothing_rather_than_crashing():
    assert parse_results("") == []
    assert parse_fiche("").is_empty()


# -- marriage-year estimate ----------------------------------------------------

class _P:
    def __init__(self, xref, birth_year):
        self.xref, self.birth_year = xref, birth_year


class _FakeTree:
    """Only the one descendant child is present -- as in a real ancestors-only tree."""

    def __init__(self, kids):
        self._kids = kids

    def children(self, xref):
        return self._kids


def test_marriage_estimate_is_not_dragged_late_by_a_non_firstborn():
    from ..apv.verify import _marriage_year

    # Joseph Segarra Ferrandis: born 1747, married 1767 per the resum. The only child
    # in the file is Francisco, born 1790 -- the fourth of seven.
    joseph = _P("I00242", 1747)
    tree = _FakeTree([_P("I00226", 1790)])
    got = _marriage_year(joseph, None, tree)
    assert got == 1771, got
    assert got < 1780, "no s'ha d'arrossegar fins al fill que hem heretat"


def test_child_year_acts_as_a_ceiling_when_they_married_young():
    from ..apv.verify import _marriage_year

    # Born 1600, but a child already in 1620: they married by 1619, not 1624.
    person = _P("X", 1600)
    tree = _FakeTree([_P("Y", 1620)])
    assert _marriage_year(person, None, tree) == 1619


def test_marriage_estimate_without_any_year_is_none():
    from ..apv.verify import _marriage_year

    assert _marriage_year(_P("X", None), None, _FakeTree([])) is None


# -- the LIVE markup, copied off the site on 30-07-2026 ------------------------
#
# This is the fiche that validated the whole pipeline: Batiste Segarra Molins,
# baptised at Fontanars 18-05-1790. Note the reference is <small>LABEL</small>
# <br><b>VALUE</b> inside ONE cell -- reading it positionally is what made the
# first version of the parser lose the book, folio and entry.

LIVE = """
<table><tbody><tr>
<td><small>SAGRAMENT</small><br><b>1</b></td>
<td><small>IDENTIFICADOR</small><br><b>2289144</b></td>
<td><small>LLIBRE</small><br><b>LB 1784-1810</b></td>
<td><small>FOLI</small><br><b>030v</b></td>
<td><small>APUNT</small><br><b>007</b></td>
<td><small>SEXE</small><br><b>H</b></td>
<td><small>SUBCON</small><br><b>0</b></td>
</tr></tbody></table>
<table><tbody>
<tr><td colspan="5">Dades de Familiars i Interessats - Restricció històrica obligatòria: 110 anys per Baptismes.</td></tr>
<tr><th>Víncle</th><th>Nom</th><th>Cognom 1</th><th>Cognom 2</th><th>Lloc Naiximent</th></tr>
<tr><td>Interessat/a</td><td>Batiste</td><td>Segarra</td><td>Molins</td><td>Fontanars dels Alforins</td></tr>
<tr><td>Cònjuge</td><td></td><td></td><td></td><td></td></tr>
<tr><td>Pare</td><td>Joan</td><td>Segarra</td><td>Alcaraz</td><td></td></tr>
<tr><td>Mare</td><td>Josepa</td><td>Molins</td><td>Alcaraz</td><td></td></tr>
<tr><td>Avi Patern</td><td>Josep</td><td>Segarra</td><td></td><td></td></tr>
<tr><td>Àvia Paterna</td><td>Josepa</td><td>Alcaraz</td><td></td><td></td></tr>
<tr><td>Avi Matern</td><td>Josep</td><td>Molins</td><td></td><td></td></tr>
<tr><td>Àvia Materna</td><td>Josepa</td><td>Alcaraz</td><td></td><td></td></tr>
</tbody></table>
<div><b>Data Naiximent</b> 18-05-1790</div>
<div><b>Professió Pare:</b> llaurador</div>
<div><b>Causa mort:</b> </div>
"""


def test_live_markup_yields_the_reference():
    f = parse_fiche(LIVE)
    assert f.get("identificador") == "2289144", f.fields
    assert f.get("book") == "LB 1784-1810", f.fields
    assert f.get("folio") == "030v"
    assert f.get("entry") == "007"
    assert f.get("sex") == "H"
    assert f.sacrament_name() == "Bateig"
    assert f.reference() == "LB 1784-1810 · 030v · 007"


def test_live_markup_does_not_pair_labels_with_labels():
    # The old bug: sacrament == "Identificador", book == "Foli".
    f = parse_fiche(LIVE)
    assert f.get("sacrament") == "1"
    assert "Identificador" not in f.fields.values()
    assert "Foli" not in f.fields.values()


def test_live_markup_yields_all_eight_kin_rows():
    f = parse_fiche(LIVE)
    person = f.person()
    assert person.full() == "Batiste Segarra Molins"
    by_role = {k.role: k.full() for k in f.kin}
    assert by_role["Pare"] == "Joan Segarra Alcaraz"
    assert by_role["Mare"] == "Josepa Molins Alcaraz"
    assert by_role["Avi Patern"] == "Josep Segarra"
    assert by_role["Àvia Materna"] == "Josepa Alcaraz"
    # The empty spouse row must not invent a person.
    assert by_role.get("Cònjuge", "") == ""


def test_live_markup_reads_the_bold_div_pairs():
    f = parse_fiche(LIVE)
    assert f.get("father_profession") == "llaurador"
    assert f.get("birth_date") == "18-05-1790"


def test_markdown_from_live_markup():
    md = to_markdown(parse_fiche(LIVE), "Batiste Segarra Molins")
    assert "LB 1784-1810" in md
    assert "Joan Segarra Alcaraz" in md
    assert "no del manuscrit original" in md


# -- encoding, as the LIVE form does it ---------------------------------------

def test_encode_is_utf8_and_accent_stripped_by_default():
    assert encode("Segarra") == "segarra"
    assert encode("Cerdà") == "cerda"
    assert encode("Ferrà") == "ferra"


def test_encode_can_keep_accents_as_utf8():
    # The live form is UTF-8; the 2025 URLs were latin-1, where this would have
    # been %F3. Getting it wrong returns zero hits rather than an error.
    assert encode("Cerdà", strip_accents=False) == "cerd%C3%A0"
    assert "%E0" not in encode("Cerdà", strip_accents=False)


def test_url_targets_the_new_endpoint_with_defaults():
    built = url(surname="Segarra", sacrament=BAPTISM, event_place="Fontanars")
    assert "llistats_genealogia_nou1.php" in built
    assert "llistats.php?" not in built
    assert "a1=segarra" in built
    assert "tipus=1" in built
    assert "filtre=P" in built
    assert "llocevento=fontanars" in built


def test_url_keeps_year_and_code_fields_literal():
    built = url(surname="Segarra", event_from=1610, event_to=1650, sex="H")
    assert "principio_evento=1610" in built
    assert "final_evento=1650" in built
    assert "sexo=H" in built



def test_ontinyent_death_hole_1729_1733():
    # Found by reading the site's live coverage table, not the printed one.
    assert coverage.covers("ontinyent", coverage.DEATH, 1725)
    assert not coverage.covers("ontinyent", coverage.DEATH, 1731)
    assert coverage.covers("ontinyent", coverage.DEATH, 1740)


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

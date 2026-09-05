"""Build the index search URLs for the diocesan index.

    >>> "a1=segar" in url(surname="Segarra", sacrament=BAPTISM)
    True

-----------------------------------------------------------------------------
THE INTERFACE CHANGED, AND THE OLD NOTES WERE WRONG
-----------------------------------------------------------------------------

This module was first written from search URLs preserved in a 2025 GEDCOM
export. Driving the live site on **30-07-2026** showed that both things those
URLs taught us are now obsolete:

  * **The endpoint moved.** `llistats.php` no longer serves results -- it falls
    through to the SDAP splash page, which is what a script sees as "no hits".
    The form now GETs `llistats_genealogia_nou1.php`, and the site is branded
    "Arxius diocesans d'Oriola-Alacant i València".
  * **The encoding flipped to UTF-8.** The old URLs used latin-1 (`a1=mic%F3`);
    the live form sends `a1=mic%C3%B3`. The page declares `charset=utf-8`.

**And a warning that outlived both.** A search for an accented surname (correctly UTF-8
encoded) returned nothing, while `a1=mic` returned 22 pages. Several terms
differed between those two attempts, so this is not proof -- but it costs
nothing to avoid, and the site's own advice points the same way: it offers `_`
as a single-character wildcard for uncertain letters. So `ascii_safe()` strips
accents by default and `filtre=P` (starts-with, the site's own default) makes
that harmless: `ferr` matches `Ferrà`, `cerda` matches `Cerdà`.

If you want the accents back, pass `strip_accents=False` and check the hit count
against a plain-ASCII run before believing a zero.

-----------------------------------------------------------------------------
THE MATCH CRITERION IS A CHOICE, AND THE DEFAULT IS THE NARROWEST OF THE THREE
-----------------------------------------------------------------------------

`filtre` used to be written once, to `P`, with no way to pass another value.
Three radio buttons on the live form, with the archive's own examples:

    P  «Coincideix principi»  Serra = Serra, Serrano…
    F  «Coincideix final»     ana   = Susana, Juana…
    C  «Conté»                toni  = Antonio, San Antonio…

**The `C` example is the case that bit us.** This index records baptisms under
the whole compound given name -- *Joan **Antoni** Soriano Sanz*, *Maria
Francesca **Josepa** Antònia Dominga Vicenta Revert Torró* -- so with `P` a
search for `nom=manuel` does not find «Vicent Manuel Revert», and the zero that
comes back is indistinguishable from a gap in the books. On 05-09-2026 two such
searches were taken for an answer; re-run **with no given name at all** the same
search returned five baptisms of siblings and unblocked four ancestors.

The gap is asymmetric, and saying so precisely is what stops good searches being
thrown away:

  * `nom=maria` **does** find «Maria Josepa Francés» -- it starts there. What
    `P` loses is «Josepa Maria Francés».
  * On **surnames** `P` costs nothing: the index ignores accents, so `torro`
    finds «Torró». The trap is the given-name field alone.

So `match=` (the form's `filtre`) is a parameter here, `P` stays the default so
nothing that already works moves, and `tools.apv.verify.plan` sends **no given
name at all** while that is so. Before writing down a zero from a search that
did carry one, re-run it with `match=CONTAINS`: a zero is a datum kept for ever,
and it is worth its being true.

**The `_` wildcard is available and always was.** The form offers `_` for a
letter you are unsure of, and `encode()` leaves it alone (it is unreserved in a
URL), so `url(surname="ferr_ndis")` reaches the archive as typed. It is the
direct way to handle an uncertain spelling -- one query instead of one per
variant -- and it is not applied automatically anywhere: knowing which letter is
in doubt is the caller's business, not this module's.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote

BASE = "https://www.arxparrvalencia.org/llistats_genealogia_nou1.php"
FORM = "https://www.arxparrvalencia.org/genealogiav_nou.php?origen=3"
SELECTIVE = FORM  # kept for callers that used the old name

# Sacrament codes, from the radio group on the live form.
BAPTISM, CONFIRMATION, MARRIAGE, DEATH, PARISH_ROLL = "1", "2", "4", "5", "6"

# How a text term is matched. P is the form's own default, and the narrowest of
# the three -- see the header for what that costs on the given-name field.
STARTS_WITH, ENDS_WITH, CONTAINS = "P", "F", "C"

# Labels as the form itself writes them, so an unknown code fails with a message
# that says what the three are instead of reaching the archive as nonsense.
MATCH_CRITERIA = {
    STARTS_WITH: "coincideix principi",
    ENDS_WITH: "coincideix final",
    CONTAINS: "conté",
}

# Every field the live form posts, in its order. Read off the form itself.
FIELDS = (
    "pagina",
    "nom", "a1", "a2",
    "nompa", "nomma", "a2p", "a2m", "a2op", "a2om",
    "nomcon", "cognomcj", "cognomq",
    "llocnaix", "lins", "llocevento", "llocpare", "llocmare", "lloctots",
    "labuopat", "labuapat", "labuomat", "labuamat", "lconyuge",
    "sexo", "principio", "final", "causa_muerte",
    "principio_evento", "final_evento",
    "direccion", "profeq", "observa",
    "tipus", "filtre", "orden",
)

# Friendly names -> form fields, so callers need not remember `a2om`.
ALIAS = {
    "given": "nom", "surname": "a1", "surname2": "a2",
    "father_given": "nompa", "mother_given": "nomma",
    "father_surname2": "a2p", "mother_surname2": "a2m",
    "gf_paternal_surname2": "a2op", "gf_maternal_surname2": "a2om",
    "spouse_given": "nomcon", "spouse_surname": "cognomcj",
    "any_surname": "cognomq",
    "birth_place": "llocnaix", "registered_place": "lins",
    "event_place": "llocevento", "any_place": "lloctots",
    "sex": "sexo",
    "birth_from": "principio", "birth_to": "final",
    "event_from": "principio_evento", "event_to": "final_evento",
    "profession": "profeq", "sacrament": "tipus",
    "match": "filtre", "order": "orden", "page": "pagina",
}

MEANING = {
    "nom": "nom de fonts", "a1": "cognom 1", "a2": "cognom 2",
    "nompa": "nom del pare", "nomma": "nom de la mare",
    "a2p": "cognom 2 del pare", "a2m": "cognom 2 de la mare",
    "a2op": "cognom 2 de l'avi patern", "a2om": "cognom 2 de l'avi matern",
    "nomcon": "nom del cònjuge", "cognomcj": "1r cognom del cònjuge",
    "cognomq": "cognom de qualsevol",
    "llocnaix": "lloc de naixement de l'interessat", "lins": "lloc d'inscripció",
    "llocevento": "lloc de l'esdeveniment", "lloctots": "lloc de qualsevol",
    "sexo": "sexe", "principio": "any de naixement des de",
    "final": "any de naixement fins a",
    "principio_evento": "any de l'esdeveniment des de",
    "final_evento": "any de l'esdeveniment fins a",
    "tipus": "sagrament", "filtre": "criteri de coincidència", "orden": "ordre",
}


# The given-name fields, which are the ones the two notes below apply to. The
# surname fields are left alone by both: the index writes surnames as the family
# wrote them, and accents aside they do not get translated.
GIVEN_NAME_FIELDS = ("nom", "nompa", "nomma", "nomcon")

# THE INDEX CATALANISES GIVEN NAMES AND MOST TREES DO NOT.
#
# Read off the live index on 05-09-2026: `nom=juan` over the Ontinyent baptisms
# returns **zero** and `nom=joan` returns **four**. Every fiche is in Valencian
# -- Antoni, Josep, Francesc, Feliu, Antònia, Miquel, Margarida -- while a
# GEDCOM exported from anywhere else usually holds the Castilian form, because
# that is how the civil registry wrote it.
#
# A zero from `nom=juan` is the same lie as a zero from a `P` match: an absence
# of the tool reported as an absence of the archive. Worse, the two compound:
# the Castilian form would not have matched even as a substring.
#
# Only the pairs that actually differ are listed, matched on the accent-stripped
# lowercase form, and a name that is not here is passed through untouched. It is
# a correspondence table, not a translator, and it is **deliberately short**:
# every entry is a Castilian/Valencian pair that is not in doubt. Guessing at
# the doubtful ones would manufacture the very thing it is here to prevent, a
# query that cannot match. For a name it does not cover, the answers are
# `match=CONTAINS` over the root of the name, or -- best of all -- no given name
# at all, which is what `verify.plan` sends.
CATALAN_GIVEN = {
    "juan": "joan", "juana": "joana",
    "jose": "josep", "josefa": "josepa",
    "francisco": "francesc", "francisca": "francesca",
    "vicente": "vicent",
    "antonio": "antoni",
    "miguel": "miquel",
    "pedro": "pere",
    "pablo": "pau",
    "jaime": "jaume",
    "jorge": "jordi",
    "margarita": "margarida",
    "catalina": "caterina",
    "ana": "anna",
    "felix": "feliu",
    "andres": "andreu",
    "bartolome": "bartomeu",
    "esteban": "esteve",
    "mateo": "mateu",
    "marcos": "marc",
    "luis": "lluis", "luisa": "lluisa",
    "lorenzo": "llorenc",
    "guillermo": "guillem",
    "bernardo": "bernat",
    "ignacio": "ignasi",
    "jeronimo": "jeroni", "geronimo": "jeroni",
    "sebastian": "sebastia",
    "cristobal": "cristofol",
    "bautista": "baptista",
    "rafael": "rafel",
    "blas": "blai",
    "eugenio": "eugeni",
    "gregorio": "gregori",
}


def ascii_safe(value: str) -> str:
    """Drop accents. See the note above on why this is the default."""
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def catalan_given(value: str) -> str:
    """The given name as the index writes it. See `CATALAN_GIVEN`.

    >>> catalan_given("Juan Bautista")
    'joan baptista'

    Word by word, because compound names mix the two languages freely and a
    whole-string table would need every combination. Anything not in the table
    comes back unchanged (accent-stripped and lowercased, as the URL wants it).
    """
    words = ascii_safe(value or "").lower().split()
    return " ".join(CATALAN_GIVEN.get(w, w) for w in words)


def encode(value: str, strip_accents: bool = True) -> str:
    """Percent-encode one term as the live form does: UTF-8."""
    text = (value or "").strip().lower()
    if strip_accents:
        text = ascii_safe(text)
    return quote(text.encode("utf-8"))


def url(strip_accents: bool = True, translate_given: bool = True, **terms) -> str:
    """Compose a search URL. Unknown keys raise rather than vanish.

    `match=` (the form's `filtre`) picks how terms are matched, and defaults to
    `STARTS_WITH` because that is the form's own default -- see the header for
    why that is the narrowest of the three and when to widen it:

    >>> "filtre=C" in url(surname="revert", match=CONTAINS)
    True

    Given names are put into the index's own spelling by `catalan_given` unless
    `translate_given=False`; surnames are never touched.
    """
    unknown = sorted(set(terms) - set(FIELDS) - set(ALIAS))
    if unknown:
        raise ValueError(f"camps que el formulari no té: {', '.join(unknown)}")

    values = {f: "" for f in FIELDS}
    values["pagina"] = "1"
    # Defaults, written before the loop precisely so that `match=` overrides
    # them. The form's own default is `P`.
    values["filtre"] = STARTS_WITH
    values["orden"] = "evento"            # by event year: most useful for us
    for key, value in terms.items():
        values[ALIAS.get(key, key)] = "" if value is None else str(value)

    if values["filtre"] not in MATCH_CRITERIA:
        raise ValueError(
            f"criteri de coincidència {values['filtre']!r} desconegut; el "
            "formulari només en té tres: "
            + ", ".join(f"{k} ({v})" for k, v in MATCH_CRITERIA.items())
        )

    parts = []
    for f in FIELDS:
        raw = values[f]
        if raw and translate_given and f in GIVEN_NAME_FIELDS:
            raw = catalan_given(raw)
        # These are codes and years, not names: never accent-strip or lowercase.
        literal = f in {"pagina", "tipus", "filtre", "orden", "sexo",
                        "principio", "final", "principio_evento", "final_evento"}
        parts.append(f"{f}={raw if literal else encode(raw, strip_accents)}")
    return f"{BASE}?{'&'.join(parts)}"


@dataclass
class Lookup:
    """One thing to go and check, and why it is worth a query."""

    xref: str
    who: str
    sacrament: str
    parish: str
    year: int | None
    what_it_would_settle: str
    url: str
    possible: bool
    note: str
    rank: int = 0
    terms: dict = field(default_factory=dict)
    # Which of the three criteria the URL carries. Part of what identifies the
    # search: the same terms under `P` and under `C` are two different questions
    # to the archive, and a zero from the narrow one does not answer the wide
    # one. `fingerprint()` reads this, so a past narrow search cannot silence a
    # wider one that has not been asked yet.
    match: str = STARTS_WITH

    def line(self) -> str:
        mark = "" if self.possible else "~~"
        year = self.year if self.year is not None else "?"
        criterion = (
            "" if self.match == STARTS_WITH
            else f"    criteri: {MATCH_CRITERIA.get(self.match, self.match)}\n"
        )
        return (
            f"{mark}**{self.who}** — {self.sacrament} {year}, {self.parish}{mark}\n"
            f"    {self.note}\n"
            f"    {self.what_it_would_settle}\n"
            f"{criterion}"
            f"    <{self.url}>"
        )

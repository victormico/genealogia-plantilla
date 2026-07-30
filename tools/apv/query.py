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

# How a text term is matched. P is the form's own default.
STARTS_WITH, ENDS_WITH, CONTAINS = "P", "F", "C"

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


def ascii_safe(value: str) -> str:
    """Drop accents. See the note above on why this is the default."""
    decomposed = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def encode(value: str, strip_accents: bool = True) -> str:
    """Percent-encode one term as the live form does: UTF-8."""
    text = (value or "").strip().lower()
    if strip_accents:
        text = ascii_safe(text)
    return quote(text.encode("utf-8"))


def url(strip_accents: bool = True, **terms) -> str:
    """Compose a search URL. Unknown keys raise rather than vanish."""
    unknown = sorted(set(terms) - set(FIELDS) - set(ALIAS))
    if unknown:
        raise ValueError(f"camps que el formulari no té: {', '.join(unknown)}")

    values = {f: "" for f in FIELDS}
    values["pagina"] = "1"
    values["filtre"] = STARTS_WITH        # the form's own default
    values["orden"] = "evento"            # by event year: most useful for us
    for key, value in terms.items():
        values[ALIAS.get(key, key)] = "" if value is None else str(value)

    parts = []
    for f in FIELDS:
        raw = values[f]
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

    def line(self) -> str:
        mark = "" if self.possible else "~~"
        year = self.year if self.year is not None else "?"
        return (
            f"{mark}**{self.who}** — {self.sacrament} {year}, {self.parish}{mark}\n"
            f"    {self.note}\n"
            f"    {self.what_it_would_settle}\n"
            f"    <{self.url}>"
        )

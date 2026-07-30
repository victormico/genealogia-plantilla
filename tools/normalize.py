"""Normalisation shared by matching, research and reporting.

The two datasets disagree in every way two genealogy files can disagree:

  the canonical tree (Ancestris)  ALL-CAPS surnames, Catalan place names, six
                                  PLAC levels as `, Town, , Province, Region,
                                  Country`, dates as `D MMM YYYY` or `YYYY`
  FamilySearch dump               Title Case surnames, Castilian exonyms
                                  (Fontanares, Onteniente, Gerona), PLAC as
                                  `Town, Province, Region, Country, ,`, plus
                                  Spanish date qualifiers (ANTES,
                                  APROXIMADAMENTE) and one ISO date

Everything here is comparison-only. Nothing normalised is ever written back to
a GEDCOM file: the canonical spellings are the ones the tree keeps.
"""

from __future__ import annotations

import re
import unicodedata

# -- text -----------------------------------------------------------------


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def fold(text: str | None) -> str:
    """Lowercase, unaccented, whitespace-collapsed. The comparison workhorse."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", strip_accents(text).lower()).strip()


# -- names ----------------------------------------------------------------

# Catalan surnames use " i " between the paternal and maternal surname
# ("PONT I PAGÉS"); Castilian ones use a bare space ("FERRER BLANCH") and
# FamilySearch sometimes inserts "y". None of it is part of the name.
_CONNECTORS = re.compile(r"\b(i|y)\b")
# Nobiliary and toponymic particles vary between sources.
_PARTICLES = re.compile(r"\b(de|del|de la|de las|de los|dels|d|la|las|los|el)\b")


def norm_surname(surname: str | None) -> str:
    s = fold(surname)
    s = s.replace("'", " ")
    s = _CONNECTORS.sub(" ", s)
    s = _PARTICLES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def surname_parts(surname: str | None) -> list[str]:
    """The individual surnames, e.g. "FERRER BLANCH" -> ["ferrer", "blanch"]."""
    return [p for p in norm_surname(surname).split(" ") if p]


# Catalan / Castilian pairs for the given names that actually occur in this
# tree, plus the ones likely to turn up as research extends the same branches.
_NAME_GROUPS = [
    {"agusti", "agustin", "agustino"},
    {"andreu", "andres"},
    {"anna", "ana"},
    {"antoni", "antonio", "antoni joan"},
    {"antonia"},
    {"bartomeu", "bartolome"},
    {"bernat", "bernardo"},
    {"carme", "carmen"},
    {"caterina", "catalina"},
    {"consol", "consuelo"},
    {"dolors", "dolores"},
    {"elena", "helena"},
    {"esteve", "esteban", "estevan"},
    {"felip", "felipe"},
    {"ferran", "fernando"},
    {"francesc", "francisco"},
    {"francesca", "francisca"},
    {"gaieta", "cayetano"},
    {"guillem", "guillermo"},
    {"jaume", "jaime"},
    {"joan", "juan"},
    {"joaquim", "joaquin"},
    {"joaquima", "joaquina"},
    {"jordi", "jorge"},
    {"josep", "jose"},
    {"josepa", "josefa"},
    {"llorenc", "lorenzo"},
    {"lluis", "luis"},
    {"lluisa", "luisa"},
    {"magdalena", "magdalena"},
    {"manuela"},
    {"margarida", "margarita"},
    {"maria"},
    {"marti", "martin"},
    {"miquel", "miguel"},
    {"montserrat", "montserrada"},
    {"narcis", "narciso"},
    {"neus", "nieves"},
    {"pasqual", "pascual"},
    {"pasquala", "pascuala"},
    {"pere", "pedro"},
    {"purificacio", "purificacion"},
    {"ramon", "raimundo"},
    {"roser", "rosario"},
    {"salvador"},
    {"teresa", "theresa"},
    {"tomas"},
    {"vicent", "vicente"},
    {"victoria"},
    {"victoria", "victoriano"},
    {"victoria", "victorià"},
    {"victorina"},
]

_VARIANTS: dict[str, frozenset[str]] = {}
for _group in _NAME_GROUPS:
    for _n in _group:
        _VARIANTS.setdefault(_n, frozenset())
        _VARIANTS[_n] = _VARIANTS[_n] | frozenset(_group)
# "Victoriano" and "Victòria" are different names; the group list above pairs
# each with "victoria" for folding, which would wrongly conflate them. Split.
_VARIANTS["victoriano"] = frozenset({"victoriano", "victoria"})
_VARIANTS["victoria"] = frozenset({"victoria", "victoriano", "victoria"})


def given_tokens(given: str | None) -> list[str]:
    """Given names as tokens, particles removed: "Juan Ramon" -> [juan, ramon].

    The canonical file writes some compound given names comma-separated
    ("Anna, Maria", "Juan, Ramon"), so commas count as separators too.
    """
    g = fold(given).replace(",", " ")
    g = re.sub(r"\bmaria del?\b", "maria", g)
    return [t for t in g.split(" ") if t and t not in {"de", "del", "la"}]


def given_variants(token: str) -> frozenset[str]:
    return _VARIANTS.get(token, frozenset({token}))


def given_match(a: str | None, b: str | None) -> float:
    """1.0 identical, 0.8 language variant, 0.5 shared first name, 0.0 no overlap."""
    ta, tb = given_tokens(a), given_tokens(b)
    if not ta or not tb:
        return 0.0
    if ta == tb:
        return 1.0
    # First given name is the one that identifies a person in these records.
    if given_variants(ta[0]) & given_variants(tb[0]):
        return 1.0 if ta[0] == tb[0] else 0.8
    # Compound names where the sources disagree on order or drop a component.
    va = {v for t in ta for v in given_variants(t)}
    vb = {v for t in tb for v in given_variants(t)}
    return 0.5 if va & vb else 0.0


# -- places ---------------------------------------------------------------

# Castilian and English exonyms seen in the FamilySearch dump, mapped to the
# Catalan/Valencian forms the canonical tree uses.
EXONYMS = {
    # Valencian towns
    "fontanares": "fontanars dels alforins",
    "fontanars": "fontanars dels alforins",
    "fontanares de los alforines": "fontanars dels alforins",
    "onteniente": "ontinyent",
    "mogente": "moixent",
    "fuente la higuera": "la font de la figuera",
    "la fuente de la higuera": "la font de la figuera",
    "bocairente": "bocairent",
    "agres": "agres",
    # Banyeres de Mariola: the dump writes it three ways, none of them the
    # town's own name. It is not in the tree yet, so this only makes sure the
    # three spellings land on one place once it is.
    "baneres": "banyeres de mariola",
    "baneras": "banyeres de mariola",
    "banyeres": "banyeres de mariola",
    "banyeres de mariola": "banyeres de mariola",
    # Provinces / regions / countries
    "valencia": "provincia de valencia",
    "provincia de valencia": "provincia de valencia",
    "alicante": "alacant",
    "alacant": "alacant",
    "comunidad valenciana": "comunitat valenciana",
    "comunitat valenciana": "comunitat valenciana",
    "catalonia": "catalunya",
    "cataluna": "catalunya",
    "catalunya": "catalunya",
    "spain": "espanya",
    "espana": "espanya",
    "espanya": "espanya",
    "france": "franca",
    "francia": "franca",
    "castilla la mancha": "castella la manxa",
    "castilla-la mancha": "castella la manxa",
    # Catalan towns with spelling drift in one source or the other
    "gerona": "girona",
    "la bisbal de ampurdan": "la bisbal d emporda",
    "la bisbal demporda": "la bisbal d emporda",
    "la bisbal d emporda": "la bisbal d emporda",
    "sant julia de ramis": "sant julia de ramis",
    "san julian de ramis": "sant julia de ramis",
    "vilasacra": "vila sacra",
    "vila-sacra": "vila sacra",
    "vila sacra": "vila sacra",
    "san miquel de campmajor": "sant miquel de campmajor",
    "sant miquel de campmajor": "sant miquel de campmajor",
    # French
    "draguinhan": "draguignan",
    "ile de porquerolles": "porquerolles",
    "porquerolles": "porquerolles",
}

# Components too broad to be evidence that two people share a birthplace.
#
# Every province the tree touches belongs here. "girona" was missing until
# 29-07-2026, and because Girona is the one province that is also a town in this
# file, the omission did real work: PlaceBook.lookup fell through to it and
# handed back the city. Provinces that share their name with their capital
# (Girona, Barcelona, Albacete) are the dangerous ones, so they go in here and
# PlaceBook.lookup allows a match only when the name comes first.
BROAD = {
    "espanya",
    "franca",
    "catalunya",
    "comunitat valenciana",
    "castella la manxa",
    "provincia de valencia",
    "girona",
    "alacant",
    "provence alpes cote dazur",
    "var",
    "albacete",
    "barcelona",
    "",
}


def norm_place_component(component: str) -> str:
    c = fold(component).replace("'", " ").replace("-", " ")
    c = re.sub(r"\s+", " ", c).strip()
    return EXONYMS.get(c, c)


def place_components(plac: str | None) -> list[str]:
    """Non-empty normalised components, most specific first.

    Both PLAC layouts in play put the most specific component first among the
    non-empty ones: the canonical file leaves the hamlet slot empty so the town
    leads, and the dump starts with the town outright.
    """
    if not plac:
        return []
    return [c for c in (norm_place_component(p) for p in plac.split(",")) if c]


def place_key(plac: str | None) -> str:
    """The most specific component, for display and grouping."""
    parts = place_components(plac)
    return parts[0] if parts else ""


def place_match(a: str | None, b: str | None) -> float:
    """1.0 same town, 0.5 same specific-ish component, 0.0 nothing in common."""
    pa, pb = place_components(a), place_components(b)
    if not pa or not pb:
        return 0.0
    # Compare the two most specific components on each side: the canonical file
    # sometimes leads with a hamlet ("El Poblet") where the dump has the town.
    head_a, head_b = set(pa[:2]) - BROAD, set(pb[:2]) - BROAD
    if not head_a or not head_b:
        return 0.0
    if pa[0] == pb[0]:
        return 1.0
    return 0.5 if head_a & head_b else 0.0


# -- dates ----------------------------------------------------------------

_QUALIFIERS = re.compile(
    r"^\s*(ABT|EST|CAL|BEF|AFT|FROM|TO|ANTES|DESPUES|APROXIMADAMENTE|CALCULADO|"
    r"ESTIMADO|ABOUT|BEFORE|AFTER|CIRCA|CA)\b\.?\s*",
    re.IGNORECASE,
)

APPROXIMATE = re.compile(
    r"\b(ABT|EST|CAL|BEF|AFT|ANTES|DESPUES|APROXIMADAMENTE|CALCULADO|ESTIMADO|"
    r"ABOUT|BEFORE|AFTER|CIRCA|CA)\b",
    re.IGNORECASE,
)


def parse_year(date_value: str | None) -> int | None:
    """First 4-digit year in a GEDCOM date, whatever dialect it is written in.

    Handles `16 NOV 1992`, `1842`, `MAR 1845`, `1992-11-16`, `ANTES 23 APR 1775`
    and `APROXIMADAMENTE 1800`.
    """
    if not date_value:
        return None
    text = _QUALIFIERS.sub("", date_value.strip())
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", text)
    return int(m.group(1)) if m else None


def is_approximate(date_value: str | None) -> bool:
    return bool(date_value and APPROXIMATE.search(date_value))


def year_match(a: int | None, b: int | None, tolerance: int = 2) -> float:
    """1.0 same year, tapering to 0.0 beyond the tolerance."""
    if a is None or b is None:
        return 0.0
    delta = abs(a - b)
    if delta == 0:
        return 1.0
    if delta > tolerance:
        return 0.0
    return 1.0 - (delta / (tolerance + 1))

"""Render new GEDCOM records in this file's own conventions.

The canonical file has a house style, and new records have to match it or the
tree becomes a patchwork:

  names    `1 NAME Josep /FERRER BLANCH/` with GIVN/SURN below, surname in caps
  dates    `17 OCT 1859`, English month abbreviations, bare year when that is
           all we know, `ABT` when the source says approximately
  places   six comma levels, `, Town, , Province, Region, Country`, with
           MAP/LATI/LONG below

Rather than invent place strings, we reuse the ones already in the file: any
town the tree already knows comes back with its exact spelling and its
coordinates. A town it does not know is emitted best-effort and flagged, so it
can be fixed once in Ancestris instead of silently drifting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gedcom.lines import GedcomFile
from .normalize import BROAD, is_approximate, norm_place_component

MONTHS = [
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
]

# Province, region and country names as this file writes them, for places the
# tree does not know yet. Keyed by the normalised form from tools.normalize.
CANONICAL_WIDER = {
    "girona": "Girona",
    "barcelona": "Barcelona",
    "catalunya": "Catalunya",
    "provincia de valencia": "Província de València",
    "alacant": "Alacant",
    "comunitat valenciana": "Comunitat Valenciana",
    "albacete": "Albacete",
    "castella la manxa": "Castella i la Manxa",
    "espanya": "Espanya",
    "franca": "França",
    "var": "Var",
}


def render_date(value: str | None) -> str | None:
    """A FamilySearch date as this file writes dates.

    `1859-10-17` -> `17 OCT 1859`, `1859-10` -> `OCT 1859`, `1859` -> `1859`.
    Text FamilySearch could not parse is kept verbatim so nothing is invented.
    An approximate source date becomes `ABT`, which the file does not yet use
    but which is proper GEDCOM 5.5.1 and is what Ancestris expects.
    """
    if not value:
        return None
    text = value.strip()
    prefix = "ABT " if is_approximate(text) else ""
    text = re.sub(r"^[A-Za-z]+\s+", "", text) if prefix else text

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    if m:
        year, month, day = m.groups()
        return f"{prefix}{int(day)} {MONTHS[int(month) - 1]} {year}"
    m = re.match(r"^(\d{4})-(\d{2})$", text)
    if m:
        year, month = m.groups()
        return f"{prefix}{MONTHS[int(month) - 1]} {year}"
    m = re.match(r"^(\d{4})$", text)
    if m:
        return f"{prefix}{text}"
    # Already in GEDCOM form, e.g. "26 DEC 1803".
    if re.match(r"^\d{1,2} [A-Z]{3} \d{4}$", text):
        return f"{prefix}{text}"
    return f"{prefix}{text}" if prefix else text


@dataclass
class PlaceBook:
    """The places the canonical file already knows, keyed by normalised town."""

    # The MAP block is stored with levels *relative to its PLAC* -- `1` for MAP
    # itself, `2` for LATI and LONG -- so that writing it back under a PLAC at any
    # level is plain addition. Storing the raw levels is what once put MAP next to
    # PLAC instead of under it, which Ancestris rejects as not GEDCOM 5.5.1.
    by_town: dict[str, tuple[str, list[tuple[int, str]]]] = field(default_factory=dict)
    unknown: set[str] = field(default_factory=set)

    @classmethod
    def from_gedcom(cls, ged: GedcomFile) -> "PlaceBook":
        book = cls()
        for i, line in enumerate(ged.lines):
            if line is None or line.tag != "PLAC" or not line.value.strip():
                continue
            plac = line.value
            # Collect the MAP block that follows, so reused places keep coordinates.
            map_lines: list[tuple[int, str]] = []
            for follower in ged.lines[i + 1 : i + 6]:
                if follower is None or follower.level <= line.level:
                    break
                map_lines.append(
                    (follower.level - line.level, follower.raw.split(" ", 1)[1])
                )
            components = [c for c in (norm_place_component(p) for p in plac.split(",")) if c]
            if not components:
                continue
            key = components[0]
            # Prefer the variant that carries coordinates.
            if key not in book.by_town or (map_lines and not book.by_town[key][1]):
                book.by_town[key] = (plac, map_lines)
        return book

    def lookup(self, place: str | None, level: int = 2) -> list[str]:
        """GEDCOM lines for a place, at the given level.

        Only the most specific component may be matched against the tree. Falling
        back to a broader one would move a person: FamilySearch's "Sant Vicenç,
        Girona, Catalonia, Spain" would match the *city* of Girona and silently
        relocate them. An unknown town is written out best-effort instead, with no
        coordinates, and reported so it can be set once in Ancestris.
        """
        if not place:
            return []
        components = [c for c in (norm_place_component(p) for p in place.split(",")) if c]
        if not components:
            return []

        # The first two components are both specific: FamilySearch writes
        # "Sant Vicenç, Cabanes, ..." where Sant Vicenç is the hamlet and Cabanes
        # the municipality, and this file has slots for both. Anything beyond
        # those is a province or wider and must never be matched.
        #
        # But a province name in SECOND place is the trap this method exists to
        # avoid, and it bit on 29-07-2026: "Terrades, Girona, Catalonia, Spain"
        # found no town called Terrades, fell through to "girona", and that IS a
        # town here -- so it returned the city of Girona and its coordinates,
        # silently moving the man forty kilometres. `BROAD` was meant to stop
        # exactly this and every province we touch was in it except Girona, the
        # one province that is also a town in this file. Which is why the hole
        # stayed invisible: for Barcelona or Albacete the fallback finds nothing
        # and lands harmlessly on best_effort.
        #
        # So position matters. A province LEADING is a real place -- somebody
        # born in the city of Girona -- and a province following is noise.
        for position, component in enumerate(components[:2]):
            if position and component in BROAD:
                continue
            hit = self.by_town.get(component)
            if hit:
                plac, map_lines = hit
                out = [f"{level} PLAC {plac}"]
                # The stored depths are relative to PLAC, so MAP lands at level+1.
                for depth, rest in map_lines:
                    out.append(f"{level + depth} {rest}")
                return out

        self.unknown.add(place)
        return [f"{level} PLAC {self.best_effort(place)}"]

    def best_effort(self, place: str) -> str:
        """An unknown place in the file's six-level layout, keeping names as written.

        This file uses `Aldea, Ciutat, Codi Postal, Comtat, Estat, País`.
        FamilySearch writes places with a varying number of levels -- four for
        "Fontanares, Valencia, Comunidad Valenciana, España" but five for
        "Sant Vicenç, Cabanes, Girona, Catalonia, Spain" -- so the wide levels are
        read from the end and the specific ones from the start. Names keep their
        original spelling; only province, region and country are translated.
        """
        parts = [p.strip() for p in place.split(",") if p.strip()]
        if not parts:
            return ""

        def wide(part: str) -> str:
            return CANONICAL_WIDER.get(norm_place_component(part), part)

        country = wide(parts[-1]) if len(parts) >= 2 else ""
        region = wide(parts[-2]) if len(parts) >= 3 else ""
        province = wide(parts[-3]) if len(parts) >= 4 else ""
        head = parts[: max(0, len(parts) - 3)] or parts[:1]
        hamlet = head[0] if len(head) >= 2 else ""
        town = head[1] if len(head) >= 2 else head[0]
        return f"{hamlet}, {town}, , {province}, {region}, {country}"

    def known(self, place: str | None) -> bool:
        return bool(self.lookup(place))


def render_name(given: str, surname: str) -> list[str]:
    """`1 NAME Josep /FERRER BLANCH/` with GIVN and SURN, surname upper-cased."""
    given = " ".join(given.split())
    surname = " ".join(surname.split()).upper()
    lines = [f"1 NAME {given} /{surname}/" if surname else f"1 NAME {given}"]
    if given:
        lines.append(f"2 GIVN {given}")
    if surname:
        lines.append(f"2 SURN {surname}")
    return lines


def render_individual(
    xref: str,
    given: str,
    surname: str,
    sex: str | None,
    birth_date: str | None = None,
    birth_place: str | None = None,
    death_date: str | None = None,
    death_place: str | None = None,
    fsftid: str | None = None,
    source_xrefs: list[str] | None = None,
    object_files: list[str] | None = None,
    famc: str | None = None,
    fams: list[str] | None = None,
    places: PlaceBook | None = None,
    change_date: str | None = None,
    change_time: str | None = None,
) -> list[str]:
    """A complete INDI record in house style. Tag order follows the file's own."""
    lines = [f"0 @{xref}@ INDI"]
    lines.extend(render_name(given, surname))
    if sex in ("M", "F"):
        lines.append(f"1 SEX {sex}")

    for tag, date, place in (("BIRT", birth_date, birth_place), ("DEAT", death_date, death_place)):
        rendered_date = render_date(date)
        place_lines = places.lookup(place) if places else []
        if not rendered_date and not place_lines:
            continue
        lines.append(f"1 {tag}")
        if rendered_date:
            lines.append(f"2 DATE {rendered_date}")
        lines.extend(place_lines)

    if famc:
        lines.append(f"1 FAMC @{famc}@")
    for fam in fams or ():
        lines.append(f"1 FAMS @{fam}@")
    for source in source_xrefs or ():
        lines.append(f"1 SOUR @{source}@")
    for path in object_files or ():
        name = path.rsplit("/", 1)[-1]
        # FORM is mandatory under FILE in GEDCOM 5.5.1, and Ancestris says so.
        form = name.rsplit(".", 1)[-1].lower() if "." in name else "pdf"
        lines.extend([f"1 OBJE", f"2 FILE {path}", f"3 FORM {form}", f"2 TITL {name}"])
    if fsftid:
        lines.append(f"1 _FSFTID {fsftid}")
    if change_date:
        lines.extend(["1 CHAN", f"2 DATE {change_date}"])
        if change_time:
            lines.append(f"3 TIME {change_time}")
    return lines


def render_family(
    xref: str,
    husband: str | None,
    wife: str | None,
    children: list[str],
    marriage_date: str | None = None,
    marriage_place: str | None = None,
    source_xrefs: list[str] | None = None,
    places: PlaceBook | None = None,
    change_date: str | None = None,
    change_time: str | None = None,
) -> list[str]:
    lines = [f"0 @{xref}@ FAM"]
    if husband:
        lines.append(f"1 HUSB @{husband}@")
    if wife:
        lines.append(f"1 WIFE @{wife}@")
    rendered_date = render_date(marriage_date)
    place_lines = places.lookup(marriage_place) if places else []
    if rendered_date or place_lines:
        lines.append("1 MARR")
        if rendered_date:
            lines.append(f"2 DATE {rendered_date}")
        lines.extend(place_lines)
    for child in children:
        lines.append(f"1 CHIL @{child}@")
    for source in source_xrefs or ():
        lines.append(f"1 SOUR @{source}@")
    if change_date:
        lines.extend(["1 CHAN", f"2 DATE {change_date}"])
        if change_time:
            lines.append(f"3 TIME {change_time}")
    return lines


def render_source(
    xref: str,
    title: str,
    url: str | None = None,
    page: str | None = None,
    text: str | None = None,
) -> list[str]:
    """A real citation, not just a bare person-detail link.

    The three sources already in the file are only a TITL and a URL. New ones
    record what was consulted and where, so a reader can check the claim.
    """
    lines = [f"0 @{xref}@ SOUR", f"1 TITL {title}"]
    if page:
        lines.append(f"1 PAGE {page}")
    if text:
        for n, chunk in enumerate(_wrap(text)):
            lines.append(f"1 TEXT {chunk}" if n == 0 else f"2 CONT {chunk}")
    if url:
        lines.append(f"1 PUBL {url}")
    return lines


def _wrap(text: str, width: int = 200) -> list[str]:
    """GEDCOM lines should stay reasonably short; split on whitespace."""
    words, out, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            out.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        out.append(current)
    return out or [""]

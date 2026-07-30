"""A comparable view of a person, extracted from either GEDCOM file.

Both files are read through tools.gedcom, so this never mutates anything. The
point is to flatten the parts that identify a person -- name, sex, vital years
and places, parents, spouses -- into one small object that tools.match can
score without caring which file it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .gedcom.lines import GedcomFile
from .normalize import (
    fold,
    given_tokens,
    is_approximate,
    norm_surname,
    parse_year,
    place_key,
    surname_parts,
)


@dataclass
class Person:
    xref: str
    name: str  # as written, e.g. "Joan /FERRER BLANCH/"
    given: str
    surname: str
    sex: str | None
    birth_date: str | None
    birth_place: str | None
    death_date: str | None
    death_place: str | None
    fsftid: str | None
    famc: str | None  # family this person is a child in
    fams: list[str] = field(default_factory=list)
    sosa: str | None = None
    source_count: int = 0

    # -- derived ----------------------------------------------------------

    @property
    def birth_year(self) -> int | None:
        return parse_year(self.birth_date)

    @property
    def death_year(self) -> int | None:
        return parse_year(self.death_date)

    @property
    def norm_surname(self) -> str:
        return norm_surname(self.surname)

    @property
    def surname_parts(self) -> list[str]:
        return surname_parts(self.surname)

    @property
    def given_tokens(self) -> list[str]:
        return given_tokens(self.given)

    @property
    def birth_town(self) -> str:
        return place_key(self.birth_place)

    @property
    def generation(self) -> int | None:
        """Sosa generation from `_SOSADABOVILLE 222 G8` -> 8."""
        if not self.sosa:
            return None
        for part in self.sosa.split():
            if part.startswith("G") and part[1:].isdigit():
                return int(part[1:])
        return None

    @property
    def is_direct_ancestor(self) -> bool:
        """d'Aboville numbers contain a dash or dot; plain Sosa numbers do not."""
        if not self.sosa:
            return False
        number = self.sosa.split()[0]
        return "-" not in number and "." not in number

    @property
    def approximate_dates(self) -> bool:
        return is_approximate(self.birth_date) or is_approximate(self.death_date)

    def label(self) -> str:
        years = ""
        if self.birth_year or self.death_year:
            years = f" ({self.birth_year or '?'}–{self.death_year or ''})".replace("–)", ")")
        town = f", {self.birth_town}" if self.birth_town else ""
        return f"{self.given} {self.surname}{years}{town}".strip()

    def __repr__(self) -> str:
        return f"<Person @{self.xref}@ {self.label()}>"


def _event(ged: GedcomFile, xref: str, tag: str) -> tuple[str | None, str | None]:
    """(date, place) of the first occurrence of an event tag."""
    events = ged.sub(xref, tag)
    if not events:
        return None, None
    date = ged.nested(events[0], "DATE", xref)
    plac = ged.nested(events[0], "PLAC", xref)
    return (
        date.value.strip() if date and date.value.strip() else None,
        plac.value.strip() if plac and plac.value.strip() else None,
    )


def load_people(ged: GedcomFile) -> dict[str, Person]:
    """Every INDI in the file, keyed by xref."""
    people: dict[str, Person] = {}
    for rec in ged.of_type("INDI"):
        xref = rec.xref
        assert xref is not None
        name_lines = ged.sub(xref, "NAME")
        name = name_lines[0].value.strip() if name_lines else ""

        # GIVN/SURN sit at level 2 under NAME in both files. Fall back to
        # splitting the slashed NAME value when they are absent.
        given = surname = ""
        if name_lines:
            g = ged.nested(name_lines[0], "GIVN", xref)
            s = ged.nested(name_lines[0], "SURN", xref)
            given = g.value.strip() if g else ""
            surname = s.value.strip() if s else ""
        if not given or not surname:
            before, _, rest = name.partition("/")
            inner, _, _after = rest.partition("/")
            given = given or before.strip()
            surname = surname or inner.strip()

        birth_date, birth_place = _event(ged, xref, "BIRT")
        # A christening is the usual proxy for a birth in these parish records.
        if not birth_date and not birth_place:
            birth_date, birth_place = _event(ged, xref, "CHR")
        death_date, death_place = _event(ged, xref, "DEAT")
        if not death_date and not death_place:
            death_date, death_place = _event(ged, xref, "BURI")

        famc_lines = ged.sub(xref, "FAMC")
        people[xref] = Person(
            xref=xref,
            name=name,
            given=given,
            surname=surname,
            sex=ged.value(xref, "SEX"),
            birth_date=birth_date,
            birth_place=birth_place,
            death_date=death_date,
            death_place=death_place,
            fsftid=ged.value(xref, "_FSFTID"),
            famc=famc_lines[0].pointer if famc_lines else None,
            fams=[ln.pointer for ln in ged.sub(xref, "FAMS") if ln.pointer],
            sosa=ged.value(xref, "_SOSADABOVILLE"),
            source_count=len(ged.sub(xref, "SOUR")),
        )
    return people


@dataclass
class Family:
    xref: str
    husband: str | None
    wife: str | None
    children: list[str]
    marriage_date: str | None
    marriage_place: str | None


def load_families(ged: GedcomFile) -> dict[str, Family]:
    families: dict[str, Family] = {}
    for rec in ged.of_type("FAM"):
        xref = rec.xref
        assert xref is not None
        husb = ged.sub(xref, "HUSB")
        wife = ged.sub(xref, "WIFE")
        date, place = _event(ged, xref, "MARR")
        families[xref] = Family(
            xref=xref,
            husband=husb[0].pointer if husb else None,
            wife=wife[0].pointer if wife else None,
            children=[ln.pointer for ln in ged.sub(xref, "CHIL") if ln.pointer],
            marriage_date=date,
            marriage_place=place,
        )
    return families


class Tree:
    """People plus families, with the relationship lookups matching needs."""

    def __init__(self, path):
        self.ged = GedcomFile(path)
        self.people = load_people(self.ged)
        self.families = load_families(self.ged)
        self.by_fsftid = {
            p.fsftid: p for p in self.people.values() if p.fsftid
        }

    def parents(self, xref: str) -> list[Person]:
        person = self.people.get(xref)
        if not person or not person.famc:
            return []
        fam = self.families.get(person.famc)
        if not fam:
            return []
        return [
            self.people[p]
            for p in (fam.husband, fam.wife)
            if p and p in self.people
        ]

    def spouses(self, xref: str) -> list[Person]:
        out = []
        for fam_xref in self.people[xref].fams:
            fam = self.families.get(fam_xref)
            if not fam:
                continue
            for candidate in (fam.husband, fam.wife):
                if candidate and candidate != xref and candidate in self.people:
                    out.append(self.people[candidate])
        return out

    def children(self, xref: str) -> list[Person]:
        out = []
        for fam_xref in self.people[xref].fams:
            fam = self.families.get(fam_xref)
            if not fam:
                continue
            out.extend(self.people[c] for c in fam.children if c in self.people)
        return out

    def leaves(self) -> list[Person]:
        """People with no parents recorded: the research frontier."""
        return [p for p in self.people.values() if not p.famc]

    def parent_surnames(self, xref: str) -> set[str]:
        return {fold(p.norm_surname) for p in self.parents(xref) if p.surname}

    def __repr__(self) -> str:
        return (
            f"<Tree {self.ged.path.name} people={len(self.people)} "
            f"families={len(self.families)} with_fsftid={len(self.by_fsftid)}>"
        )

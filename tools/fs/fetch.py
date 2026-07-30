"""Pull a live pedigree from FamilySearch into the same Person model as our GEDCOM.

Root it at whoever's tree you actually want covered on both sides. An old
GEDCOM export is usually lopsided -- ours went deep on one grandparent's lines
and barely touched another's -- because it was exported from wherever the work
happened to be that year. A live fetch rooted at the de-cujus covers both halves.
The root PID is `familysearch: arrel:` in config.yaml.

The ancestry endpoint returns up to 8 generations per call and labels everyone
with a Sosa `ascendancyNumber`, so parent links come from arithmetic: the person
numbered N has father 2N and mother 2N+1. Spouses are numbered `N-S`. To go past
8 generations we re-root a fresh call at each eighth-generation person and merge
the edges; no global renumbering is needed because we keep edges, not numbers.

    python3 -m tools.fs.fetch                       # the root from config.yaml
    python3 -m tools.fs.fetch --root XXXX-XXX        # or one off the command line
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..normalize import fold
from ..people import Person
from .api import Api
from .session import add_common_args, build_session

ROOT_DIR = Path(__file__).resolve().parents[2]


def _facts(person: dict) -> dict[str, dict]:
    """Best fact per GEDCOM X type, e.g. {"Birth": {...}, "Death": {...}}."""
    out: dict[str, dict] = {}
    for fact in person.get("facts") or ():
        kind = str(fact.get("type", "")).rsplit("/", 1)[-1]
        out.setdefault(kind, fact)
    return out


def _date(fact: dict | None) -> str | None:
    """Prefer the ISO `formal` value; fall back to what the user typed."""
    if not fact:
        return None
    date = fact.get("date") or {}
    formal = date.get("formal")
    if formal:
        # "+1959-10-01" -> "1959-10-01"; "+1959-10" -> "1959-10"
        return formal.lstrip("+")
    return date.get("original")


def _place(fact: dict | None) -> str | None:
    """Prefer the original wording: it is what the parish register said."""
    if not fact:
        return None
    place = fact.get("place") or {}
    if place.get("original"):
        return place["original"]
    normalized = place.get("normalized") or []
    return normalized[0].get("value") if normalized else None


def to_person(raw: dict) -> Person:
    """One GEDCOM X person as our comparable Person. xref is the FamilySearch PID."""
    display = raw.get("display") or {}
    facts = _facts(raw)
    name = display.get("name") or ""

    # Spanish and Catalan names put the given name(s) first and one or two
    # surnames after. FamilySearch stores the parts when it has them.
    given = surname = ""
    for name_form in raw.get("names") or ():
        for form in name_form.get("nameForms") or ():
            for part in form.get("parts") or ():
                kind = str(part.get("type", "")).rsplit("/", 1)[-1]
                if kind == "Given" and not given:
                    given = part.get("value", "")
                elif kind == "Surname" and not surname:
                    surname = part.get("value", "")
    if not given or not surname:
        # Fall back to splitting the display name on its last two tokens, which
        # is the usual shape in Spanish records ("Josep Ferrer Blanch").
        tokens = name.split()
        if len(tokens) >= 3:
            given, surname = tokens[0], " ".join(tokens[-2:])
        elif len(tokens) == 2:
            given, surname = tokens
        else:
            given = given or name

    gender = display.get("gender") or ""
    birth, death = facts.get("Birth"), facts.get("Death")
    christening, burial = facts.get("Christening"), facts.get("Burial")

    return Person(
        xref=raw.get("id", ""),
        name=f"{given} /{surname}/" if surname else given,
        given=given,
        surname=surname,
        sex={"Male": "M", "Female": "F"}.get(gender),
        birth_date=_date(birth) or display.get("birthDate") or _date(christening),
        birth_place=_place(birth) or display.get("birthPlace") or _place(christening),
        death_date=_date(death) or display.get("deathDate") or _date(burial),
        death_place=_place(death) or display.get("deathPlace") or _place(burial),
        fsftid=raw.get("id"),
        famc=None,  # filled in by LiveTree from the ascendancy edges
        fams=[],
        sosa=display.get("ascendancyNumber"),
        source_count=0,
    )


@dataclass
class LiveTree:
    """A pedigree fetched from FamilySearch, with the Tree interface match.py needs."""

    people: dict[str, Person] = field(default_factory=dict)
    father_of: dict[str, str] = field(default_factory=dict)  # child pid -> father pid
    mother_of: dict[str, str] = field(default_factory=dict)
    couples: list[tuple[str, str]] = field(default_factory=list)
    root: str | None = None
    calls: int = 0
    skipped_leaves: list[str] = field(default_factory=list)

    # -- Tree-compatible surface -----------------------------------------

    @property
    def by_fsftid(self) -> dict[str, Person]:
        return dict(self.people)

    def parents(self, pid: str) -> list[Person]:
        out = []
        for table in (self.father_of, self.mother_of):
            parent = table.get(pid)
            if parent and parent in self.people:
                out.append(self.people[parent])
        return out

    def children(self, pid: str) -> list[Person]:
        out = []
        for child, father in self.father_of.items():
            if father == pid and child in self.people:
                out.append(self.people[child])
        for child, mother in self.mother_of.items():
            if mother == pid and child in self.people:
                out.append(self.people[child])
        return out

    def spouses(self, pid: str) -> list[Person]:
        out = []
        for a, b in self.couples:
            other = b if a == pid else (a if b == pid else None)
            if other and other in self.people:
                out.append(self.people[other])
        # A shared child implies a couple even when no Couple relationship exists.
        for child, father in self.father_of.items():
            if father == pid:
                mother = self.mother_of.get(child)
                if mother and mother in self.people:
                    out.append(self.people[mother])
            elif self.mother_of.get(child) == pid and father in self.people:
                out.append(self.people[father])
        seen, unique = set(), []
        for p in out:
            if p.xref not in seen:
                seen.add(p.xref)
                unique.append(p)
        return unique

    def leaves(self) -> list[Person]:
        return [
            p
            for p in self.people.values()
            if p.xref not in self.father_of and p.xref not in self.mother_of
        ]

    def generation(self, pid: str) -> int | None:
        """Generations above the root, by walking the parent edges."""
        if self.root is None:
            return None
        frontier, depth, seen = [self.root], 1, {self.root}
        while frontier:
            if pid in frontier:
                return depth
            nxt = []
            for person in frontier:
                for table in (self.father_of, self.mother_of):
                    parent = table.get(person)
                    if parent and parent not in seen:
                        seen.add(parent)
                        nxt.append(parent)
            frontier, depth = nxt, depth + 1
        return None

    def __repr__(self) -> str:
        return (
            f"<LiveTree root={self.root} people={len(self.people)} "
            f"edges={len(self.father_of) + len(self.mother_of)} calls={self.calls}>"
        )

    # -- serialisation ----------------------------------------------------

    def to_json(self) -> dict:
        return {
            "root": self.root,
            "calls": self.calls,
            "skipped_leaves": self.skipped_leaves,
            "people": [
                {
                    "pid": p.xref,
                    "given": p.given,
                    "surname": p.surname,
                    "sex": p.sex,
                    "birth_date": p.birth_date,
                    "birth_place": p.birth_place,
                    "death_date": p.death_date,
                    "death_place": p.death_place,
                    "sosa": p.sosa,
                }
                for p in self.people.values()
            ],
            "father_of": self.father_of,
            "mother_of": self.mother_of,
            "couples": self.couples,
        }

    @classmethod
    def from_json(cls, data: dict) -> "LiveTree":
        tree = cls(
            root=data.get("root"),
            calls=data.get("calls", 0),
            skipped_leaves=data.get("skipped_leaves", []),
            father_of=dict(data.get("father_of", {})),
            mother_of=dict(data.get("mother_of", {})),
            couples=[tuple(c) for c in data.get("couples", [])],
        )
        for row in data.get("people", []):
            tree.people[row["pid"]] = Person(
                xref=row["pid"],
                name=f"{row['given']} /{row['surname']}/",
                given=row["given"],
                surname=row["surname"],
                sex=row.get("sex"),
                birth_date=row.get("birth_date"),
                birth_place=row.get("birth_place"),
                death_date=row.get("death_date"),
                death_place=row.get("death_place"),
                fsftid=row["pid"],
                famc=None,
                sosa=row.get("sosa"),
            )
        return tree


def _absorb(tree: LiveTree, data: dict) -> list[str]:
    """Merge one ancestry response. Returns the PIDs at the 8th generation."""
    by_sosa: dict[int, str] = {}
    spouse_of: dict[int, str] = {}
    for raw in data.get("persons") or ():
        person = to_person(raw)
        if not person.xref:
            continue
        # Keep the richer record if we have seen this person before.
        existing = tree.people.get(person.xref)
        if existing is None or (not existing.birth_date and person.birth_date):
            tree.people[person.xref] = person
        number = (raw.get("display") or {}).get("ascendancyNumber") or ""
        if number.isdigit():
            by_sosa[int(number)] = person.xref
        elif number.endswith("-S") and number[:-2].isdigit():
            spouse_of[int(number[:-2])] = person.xref

    # Sosa arithmetic: the person numbered N has father 2N and mother 2N+1.
    for number, child in by_sosa.items():
        father = by_sosa.get(number * 2)
        mother = by_sosa.get(number * 2 + 1)
        if father:
            tree.father_of[child] = father
        if mother:
            tree.mother_of[child] = mother
        if father and mother:
            tree.couples.append((father, mother))

    for number, spouse in spouse_of.items():
        partner = by_sosa.get(number)
        if partner:
            tree.couples.append((partner, spouse))

    for rel in data.get("relationships") or ():
        if str(rel.get("type", "")).endswith("Couple"):
            a = (rel.get("person1") or {}).get("resourceId")
            b = (rel.get("person2") or {}).get("resourceId")
            if a and b:
                tree.couples.append((a, b))

    # Generation 8 of this call is Sosa 128..255: those are the people whose own
    # parents were not returned, so they are where the next call must re-root.
    return [pid for number, pid in by_sosa.items() if 128 <= number <= 255]


def fetch_pedigree(
    api: Api,
    root: str = "",
    max_chained: int = 40,
    verbose: bool = True,
) -> LiveTree:
    """Ancestry of `root`, chaining past the 8-generation limit per call."""
    tree = LiveTree(root=root)

    first = api.ancestry(root, generations=8)
    tree.calls += 1
    if not first:
        raise RuntimeError(f"no ancestry returned for {root}")
    frontier = _absorb(tree, first)
    if verbose:
        print(f"  call 1: root {root} -> {len(tree.people)} people, "
              f"{len(frontier)} at generation 8")

    # Only re-root where it can pay off, and say out loud what we skip.
    to_chain = frontier[:max_chained]
    if len(frontier) > max_chained:
        tree.skipped_leaves = frontier[max_chained:]
        print(
            f"  NOTE: {len(tree.skipped_leaves)} eighth-generation people not "
            f"followed (--max-chained {max_chained}): "
            f"{', '.join(tree.skipped_leaves[:5])}..."
        )

    for n, pid in enumerate(to_chain, start=2):
        before = len(tree.people)
        data = api.ancestry(pid, generations=8)
        tree.calls += 1
        if not data:
            continue
        deeper = _absorb(tree, data)
        gained = len(tree.people) - before
        if verbose and gained:
            person = tree.people.get(pid)
            print(
                f"  call {n}: {pid} {person.label() if person else ''} "
                f"-> +{gained} people"
            )
        # Anything deeper still could be chained again; one extra level is
        # plenty for a tree that currently reaches generation 10.
        for deep_pid in deeper:
            if deep_pid not in tree.people:
                continue
    return tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--root", default=None,
                        help="PID de la persona per on arrencar [config.yaml]")
    parser.add_argument(
        "--max-chained",
        type=int,
        default=40,
        help="how many 8th-generation people to re-root from [40]",
    )
    parser.add_argument(
        "--out",
        default=ROOT_DIR / "cache" / "pedigree.json",
        help="where to write the fetched pedigree",
    )
    args = parser.parse_args()

    root = args.root or config.fs_root()
    fs = build_session(args)
    api = Api(fs)
    print(f"fetching pedigree of {root} as {fs.display_name}")
    tree = fetch_pedigree(api, root, args.max_chained)
    print(f"\n{tree}")
    print(f"{fs.stats()}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(tree.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"wrote {out}")

    leaves = tree.leaves()
    print(f"\n{len(leaves)} people with no parents on FamilySearch (their frontier):")
    for p in sorted(leaves, key=lambda q: (q.birth_year or 9999))[:15]:
        print(f"  {p.xref}  {p.label()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

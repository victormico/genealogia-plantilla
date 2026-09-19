"""Who is probably still alive, and therefore is not archive work.

A tree's dead ends are not all the same kind of problem. Most of them are
ancestors: the parish book is the only thing that can name their parents, and
the whole research frontier is about which book to open first. A few of them
are the living -- a spouse who married in, a parent-in-law, someone's partner
-- and for those the frontier's advice is wrong in every particular:

  * **The archives cannot help.** Parish and civil registers are closed for
    decades precisely to protect the living, so "go to the Arxiu Diocesà" is
    not a lead, it is a dead end with a plausible name on it.
  * **FamilySearch hides them.** Living people are private there by design:
    a record search for one returns nothing, always, and "primer cal trobar-la
    a FamilySearch" is advice that cannot succeed.
  * **Somebody in the family knows.** Their parents are not lost, just not
    typed in yet. The fix is a phone call, not a search.

Mixing them into the same ranked queue makes the queue lie about its own size
and sends whoever works it to an archive to look for a person who is alive.
So they are classified apart, before anything else, and this module is where
that judgement is made.

**It is a judgement, not a fact.** A GEDCOM rarely says "alive": it says a
birth date, or nothing at all. So:

  1. A recorded death -- `DEAT`/`BURI`, a date or just a place -- settles it.
  2. Otherwise, a birth year less than `llindar_anys` ago (100 by default,
     `contemporanis:` in config.yaml) means presumed living.
  3. With no birth year, the year is estimated from the relatives who do have
     one, a generation being 30 years, taking the nearest such relative. That
     is how a person with no dates at all whose son was born in 1993 comes out
     presumed living, which is the right answer and the one a reader would
     give.
  4. If nothing in their branch has a date either, nobody is presumed living:
     an undated person in an undated corner of a tree that goes back to the
     16th century is far likelier to be long dead than newborn.

Every verdict carries the reason that produced it, so a report can print
"any estimat cap al 1963 a partir de Josep RIBERA VANYÓ (n. 1993)" instead of
asking to be trusted.

    from .living import presumed_living
    verdicts = presumed_living(tree)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from .people import Tree

# Years between a parent's birth and a child's, for estimating from relatives.
# Only ever used to decide "this century or an earlier one", so being a few
# years out either way changes no answer.
GENERATION = 30

# Years after a birth beyond which a person with no recorded death is presumed
# dead anyway. 100 is the usual genealogical convention and matches what the
# civil registers use to open a record to the public. `contemporanis:` in
# config.yaml overrides it.
DEFAULT_THRESHOLD = 100

# How far an estimate may travel through relatives before it stops being worth
# anything: each step is one family joined, and four already reaches across a
# spouse, their parents and a cousin. Beyond that the 30-year generation has
# been applied so many times that the answer is the tree's average, not this
# person's, and a wrong "presumed living" is worse than no verdict.
MAX_STEPS = 4


@dataclass(frozen=True)
class Estimate:
    """A birth year and where it came from."""

    year: int
    steps: int  # 0 = the person's own recorded date
    # Who the year came from, for the report: "Josep RIBERA VANYÓ (n. 1993)".
    # Deliberately the source person and not the relationship to them: the same
    # estimate travels on to a spouse and to a child, and a word that is right
    # for one of them is wrong for the other.
    basis: str

    @property
    def is_own(self) -> bool:
        return self.steps == 0


def _own_estimate(tree: Tree, xref: str) -> Estimate | None:
    """What the person's own record says, if it says anything about a year."""
    person = tree.people[xref]
    if person.birth_year:
        return Estimate(person.birth_year, 0, f"nascut/da el {person.birth_date}")
    if person.death_year:
        # Born some decades before they died: enough to place the century.
        return Estimate(
            person.death_year - 60, 0, f"mort/a el {person.death_date}"
        )
    return None


def _de(name: str) -> str:
    """`de Carmen`, but `d'Antonio`: Catalan elides before a vowel."""
    first = name.lstrip("«\"'").lower()[:1]
    return f"d'{name}" if first in "aeiouàèéíòóúh" else f"de {name}"


def _basis(tree: Tree, xref: str, estimate: Estimate) -> str:
    """How to name the relative an estimate came from.

    Their own recorded year is worth printing; an estimate of theirs is not,
    so the chain stays at one name deep however far it travelled.
    """
    person = tree.people[xref]
    name = f"{person.given} {person.surname}".strip() or f"@{xref}@"
    return f"{name} (n. {estimate.year})" if estimate.is_own else name


def estimated_births(tree: Tree) -> dict[str, Estimate]:
    """Everyone's birth year, recorded where there is one and inferred where not.

    Inference spreads outwards from the people who have a date, one family at
    a time, so the estimate a person ends up with is the one from the closest
    relative who actually has a date -- and `Estimate.steps` says how far it
    travelled. A single pass would give whoever happened to be visited first;
    going breadth-first is what makes the answer independent of xref order.
    """
    known: dict[str, Estimate] = {}
    for xref in tree.people:
        own = _own_estimate(tree, xref)
        if own:
            known[xref] = own

    for step in range(1, MAX_STEPS + 1):
        found: dict[str, Estimate] = {}
        for family in tree.families.values():
            spouses = [x for x in (family.husband, family.wife) if x in tree.people]
            children = [c for c in family.children if c in tree.people]

            # The best-known year for this household, as a couple's birth year.
            best: Estimate | None = None
            for xref in spouses:
                candidate = known.get(xref)
                if candidate and (best is None or candidate.steps < best.steps):
                    best = Estimate(
                        candidate.year, candidate.steps, _basis(tree, xref, candidate)
                    )
            for xref in children:
                candidate = known.get(xref)
                if candidate and (best is None or candidate.steps < best.steps):
                    best = Estimate(
                        candidate.year - GENERATION,
                        candidate.steps,
                        _basis(tree, xref, candidate),
                    )
            if best is None:
                continue

            def offer(xref: str, year: int, source: Estimate = best) -> None:
                """Hand this household's year to a member who has none yet.

                `source` is bound as a default rather than closed over: the
                loop rebinds `best` on the next family, and a closure would
                make the estimate depend on when it happened to be read.
                """
                if xref in known:
                    return
                previous = found.get(xref)
                if previous is None or previous.steps > source.steps + 1:
                    found[xref] = Estimate(year, source.steps + 1, source.basis)

            for xref in spouses:
                offer(xref, best.year)
            for xref in children:
                offer(xref, best.year + GENERATION)

        if not found:
            break
        known.update(found)

    return known


def threshold() -> int:
    """Years since birth after which someone is presumed dead. See config.yaml."""
    from . import config

    raw = config.get("contemporanis", "llindar_anys", default=DEFAULT_THRESHOLD)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return value if value > 0 else DEFAULT_THRESHOLD


@dataclass(frozen=True)
class Verdict:
    """Why one person counts as contemporary, in words the report can print."""

    estimate: Estimate
    reason: str


def presumed_living(
    tree: Tree,
    *,
    limit: int | None = None,
    today: datetime.date | None = None,
) -> dict[str, Verdict]:
    """Everyone in the tree who is probably still alive, and why.

    A recorded death always wins: no estimate overrides a burial. Everything
    else is the birth-year rule, on the person's own date where there is one
    and on an inferred one otherwise.
    """
    limit = threshold() if limit is None else limit
    year_now = (today or datetime.date.today()).year
    births = estimated_births(tree)

    out: dict[str, Verdict] = {}
    for xref, person in tree.people.items():
        if person.death_date or person.death_place:
            continue  # a death recorded is a death, whatever the arithmetic says
        estimate = births.get(xref)
        if estimate is None:
            continue  # nothing in their branch has a date: not a claim to make
        if year_now - estimate.year >= limit:
            continue
        if estimate.is_own:
            # The year, not the full date. A living person's exact birth date
            # is the one fact in this tree that is worth nothing to the
            # research and everything to somebody impersonating them, and a
            # generated report is the copy most likely to get pasted
            # somewhere else. It stays in the GEDCOM, where it belongs.
            reason = f"nascut/da el {estimate.year}"
        else:
            reason = (
                f"sense dates; any estimat cap al {estimate.year} a partir "
                f"{_de(estimate.basis)}"
            )
        out[xref] = Verdict(estimate, reason)
    return out

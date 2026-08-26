"""Bottom-up verification: which ancestors the diocesan index can still settle.

Walks **every ancestor in Sosa order, lowest first**, and works out for each one
whether the index can document them and with which sacrament.

Bottom-up is the right direction for a reason. If the nearest unverified
generation turns out wrong, nothing above it is worth a query; verifying
downward from the oldest name spends the day's queries on the least certain end.

**It used to walk one surname's male line**, from the deepest documented person
upward, and that hid the real gap: a count on 31-07-2026 found 140 of 227
ancestors with no archive source at all -- including six in the fourth and fifth
generations, who had nothing, not even FamilySearch -- while the one spine it
did walk was documented back to a man born in 1562. A seventeen-storey tower on
wooden foundations.

So the order is the plain one: **Sosa 1 upward, skipping whoever an archive
already documents**. Any one line is still in there; it is just no longer the
only thing looked at.

    python3 -m tools.apv.verify                  # the plan, no requests
    python3 -m tools.apv.verify --quota          # how many queries are left today
    python3 -m tools.apv.verify --top 5 --fetch  # actually look up the first five

Without `--fetch` this makes no requests at all.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import re

from .. import config
from ..config import tree_path
from ..people import Tree
from . import coverage
from . import query
from .query import Lookup, SELECTIVE, url
from .session import Challenged, QuotaExhausted, add_common_args, build_session

from ..config import ROOT
REPORT = ROOT / "reports" / "apv-verificacio.md"


def root_person(tree: Tree) -> str | None:
    """Sosa 1: the person the whole walk counts from.

    `estat: arrel:` in config.yaml if it is set, and otherwise whoever Ancestris
    has already marked `_SOSADABOVILLE 1`, which is the same answer without
    anybody having to type an xref twice.
    """
    chosen = config.estat_root()
    if chosen:
        return chosen
    for person in tree.people.values():
        if person.sosa and person.sosa.split()[0] == "1":
            return person.xref
    return None

# Parishes and spans whose MARRIAGE books are LOST are `apv: llibres_perduts:`
# in config.yaml, because which books a fire or a war took is per-parish
# history. Where the book is gone, what the index holds is the gutting of a
# «Libro Índice», and that changes what a query buys:
#
#   * one surname per person, so `a2` can only exclude -- see the marriage URL
#   * the father of the interested party, and NOTHING else: no mother, no
#     grandparents, no parents of the spouse
#   * no image to request afterwards, because the book does not exist
#
# It matters for ORDER, not just for wording. The obvious rule is "marriage
# first, always", on the grounds that a marriage gives parents plus four
# grandparents for both spouses while baptisms have holes. **For a lost span
# that is backwards**: a marriage there yields one name, and a baptism from a
# book that still exists yields seven.


def marriage_book_is_lost(parish: str, year: int | None) -> bool:
    if year is None:
        return False
    return any(parish == p and lo <= year <= hi
               for p, lo, hi in config.apv_lost_marriage_books())


def _birth_year_is_documented(person) -> bool:
    """Does the birth year come from a record, or is it somebody's estimate?

    A bare «1775» is an estimate -- FamilySearch hands them out by the round
    number, and three different ancestors of ours carry that exact one. A
    «20 SEP 1684» was read off a partida. The distinction decides how wide the
    baptism window should be, and getting it wrong is not symmetric: ±2 around a
    fabricated year is a near-guaranteed zero, which then reads as «this ancestor
    is not in the index».

    It is the same lesson as the marriage of 1850, which the plan put at 1845 and
    which only turned up because that window was ±8.
    """
    raw = (person.birth_date or "").strip()
    # More than a year in there -- a month name or a day -- means a real date.
    return bool(raw) and not re.fullmatch(r"\d{3,4}", raw)

# Which folders of `Fonts/` hold transcribed archive records is
# `apv: carpetes_arxiu:` in config.yaml. A person named in any `.md` inside them
# has been looked up already, whether or not the GEDCOM says so -- see
# `already_transcribed`.
_XREF_IN_TEXT = re.compile(r"@(I\d+)@")

# An escape hatch a transcription can use to say "I mention this person only to
# record that this fiche does NOT document them". Without it, naming somebody in
# order to deny them marks them as looked-up and drops them from the plan --
# found on 03-08-2026, writing up the 1823 marriage: its own "what it does NOT
# establish" section quietly hid three ancestors.
#
#   <!-- apv:no-documenta I00161 I00162 I00163 -->
_NOT_DOCUMENTED = re.compile(r"apv:no-documenta([^\-]*)")


def plan(tree: Tree) -> list[Lookup]:
    """One ranked lookup per undocumented ancestor, lowest Sosa first."""
    out: list[Lookup] = []

    for depth, (sosa, person) in enumerate(undocumented_ancestors(tree)):
        spouses = tree.spouses(person.xref)
        parents = tree.parents(person.xref)
        parish = _parish_of(person, tree)

        # A marriage fiche normally gives the searched person's parents AND four
        # grandparents, and some parishes' marriages are complete where the
        # baptisms have two big holes -- which is why this used to say "marriage
        # first, always". It no longer does: where the marriage book is LOST the
        # apunt yields the father alone, and the baptism outranks it. See
        # `apv: llibres_perduts:` in config.yaml.
        for spouse in spouses or [None]:
            year = _marriage_year(person, spouse, tree)
            verdict = coverage.covers(parish, coverage.MARRIAGE, year)
            lost_book = marriage_book_is_lost(parish, year)
            settles = (
                f"donaria el PARE de {person.given} —el llibre és perdut i l'índex "
                f"no en dona més" if lost_book else
                f"donaria els pares i els quatre avis de {person.given}"
                if not parents else
                f"confirmaria o desmentiria {', '.join(p.given + ' ' + p.surname for p in parents)}"
            )
            out.append(Lookup(
                xref=person.xref, who=_label(person),
                sacrament=coverage.MARRIAGE, parish=parish, year=year,
                what_it_would_settle=settles,
                # NO given name. The LLEGIU-ME of the index has said since
                # 28-07-2026 that a name typed the way we spell it and not the
                # way the index does returns zero and spends a query all the
                # same -- `nom=eustaqui` for a man the index calls Enric. On
                # 01-08-2026 this tool still sent one, and it cost two more.
                #
                # AND NO SECOND SURNAME EITHER, for a marriage. Proven on
                # 03-08-2026: the same search with `a2=sanchis` returned zero and
                # without it returned three fiches, one of them the marriage we
                # were after. The reason is in the books, not in the form -- both
                # marriage books of the span concerned
                # are LOST, and what the index holds is the gutting of a Libro
                # Índice that recorded ONE surname per person. Every fiche from
                # them has an empty «Cognom 2», so `a2` can only ever exclude.
                #
                # It is safe in general, not just there: `a1` + the spouse's
                # surname + parish + a year window is already selective enough
                # that the result sets run to a handful, and dropping `a2` cannot
                # lose a hit -- it can only add noise we then read.
                url=url(surname=_first(person.surname),
                        spouse_surname=_first(spouse.surname) if spouse else "",
                        event_place=parish,
                        sacrament=query.MARRIAGE,
                        # A ±8 year window: the year is an estimate, so pinning
                        # it exactly would hide the real record.
                        event_from=year - 8 if year else "",
                        event_to=year + 8 if year else ""),
                possible=bool(verdict), note=(
                    verdict.why + (
                        ". ATENCIÓ: el llibre de matrimonis d'aquests anys és PERDUT, "
                        "o siga que l'apunt donarà el PARE de l'interessat i res més "
                        "—ni mare, ni avis, ni els pares del cònjuge— i no hi haurà "
                        "cap imatge a demanar. El bateig val set persones i va primer"
                        if lost_book else ""
                    )
                ),
                # Order: normally the marriage leads, because it settles both
                # spouses at once. Where the marriage book is lost it yields one
                # name, so the baptism takes the lead instead.
                rank=depth * 10 + (2 if lost_book else 0),
                terms={"a1": _first(person.surname),
                       "a2": "",
                       "cognomcj": _first(spouse.surname) if spouse else "",
                       "from": year - 8 if year else None,
                       "to": year + 8 if year else None},
            ))

        # Then the baptism, which is the direct evidence for the person's own
        # parents when the years fall inside a covered span.
        byear, hops = _birth_year_estimate(person, tree)
        verdict = coverage.covers(parish, coverage.BAPTISM, byear)
        # ±2 around a date read off a partida; ±8 around somebody's estimate. See
        # `_birth_year_is_documented`: a tight window on a fabricated year returns
        # zero and the zero then reads as "not in the index".
        #
        # And wider still when the year came from counting generations DOWN to a
        # dated descendant: each hop is another thirty-year guess that leans late.
        exact = _birth_year_is_documented(person)
        span = 2 if exact else 8 + 6 * hops
        out.append(Lookup(
            xref=person.xref, who=_label(person),
            sacrament=coverage.BAPTISM, parish=parish, year=byear,
            what_it_would_settle=f"la seva pròpia partida: pares i quatre avis de {person.given}",
            url=url(surname=_first(person.surname),
                    surname2=_second(person.surname), event_place=parish,
                    sacrament=query.BAPTISM,
                    event_from=byear - span if byear else "",
                    event_to=byear + span if byear else ""),
            possible=bool(verdict), note=(
                verdict.why + ("" if exact else
                               f". L'any de naixement és una ESTIMACIÓ i no ve de cap "
                               f"document, o siga que la forquilla va a ±{span} anys"
                               + (f" —i surt de comptar {hops} generaci"
                                  f"{'ons' if hops > 1 else 'ó'} cap avall fins a un "
                                  f"descendent datat, o siga que tira a tard"
                                  if hops else ""))
            ),
            rank=depth * 10 + 1,
            terms={"a1": _first(person.surname),
                   "a2": _second(person.surname),
                   "from": byear - span if byear else None,
                   "to": byear + span if byear else None},
        ))

    # A search already made -- above all one that came back empty, which leaves
    # no transcription behind -- stops being possible. See `asked_before`.
    log = asked_before()
    for lookup in out:
        past = _matches_a_past_search(lookup, log) if lookup.possible else None
        if past:
            who = " × ".join(past["couple"]) or " ".join(
                t for t in (past.get("a1"), past.get("a2")) if t)
            lookup.possible = False
            lookup.note = (
                f"JA S'HA DEMANAT: {past['sacrament']} {who} a {past['parish']}, "
                f"{past['from']}-{past['to']}. El registre de "
                f"`cache/apv-quota.json` ho diu, i una consulta no es paga dues vegades"
            )

    out.sort(key=lambda l: (not l.possible, l.rank))
    return out


def render(lookups: list[Lookup], quota: str) -> str:
    doable = [l for l in lookups if l.possible]
    blocked = [l for l in lookups if not l.possible]
    spent = [l for l in blocked if l.note.startswith("JA S'HA DEMANAT")]
    lines = [
        "# Verificació de baix a dalt contra l'índex diocesà",
        "",
        "Generat per `python3 -m tools.apv.verify`. **Aquest fitxer es regenera**; el",
        "raonament va als fitxers de cas.",
        "",
        f"**{quota}**",
        "",
        f"De les {len(lookups)} comprovacions possibles sobre paper, **{len(doable)} es poden",
        f"demanar de veres** i {len(blocked)} no, perquè cauen en un forat de l'índex, en",
        "l'embargament legal, o perquè **ja s'han demanat**. L'ordre és de baix a dalt:",
        "**si un graó falla, els de damunt no valen una consulta.**",
        "",
    ]
    if spent:
        lines += [
            f"> **{len(spent)} d'aquestes ja s'han demanat i surten de la llista.** Les que",
            "> van tornar buides no deixen cap transcripció a `Fonts/`, o siga que abans de",
            "> el 03-08-2026 es tornaven a proposar cada vegada que es regenerava el pla. Ara",
            "> es creuen amb el registre de `cache/apv-quota.json`, que és l'únic lloc on",
            "> consta una cerca sense resultat. **Un zero és una troballa, i no es paga dues",
            "> vegades.**",
            "",
        ]
    lines += [
        "> Recorda el que va passar amb el matrimoni del 1894: **que l'índex tinga",
        "> l'apunt no vol dir que el llibre tinga la partida.** Amb el número de",
        "> registre a la mà, el manuscrit es demana a l'Arxiu Diocesà de València.",
        "",
        f"Cerca selectiva, per si vols escriure-hi a mà: <{SELECTIVE}>",
        "",
        "## Es poden demanar, per ordre",
        "",
    ]
    for n, l in enumerate(doable, 1):
        lines += [f"### {n}. {l.line()}", ""]
    lines += ["## No es poden demanar, i per què", ""]
    for l in blocked:
        year = l.year if l.year is not None else "?"
        lines.append(f"- **{l.who}** — {l.sacrament} {year}, {l.parish}: {l.note}")
    lines += [
        "",
        "### Què fer amb els que no es poden demanar",
        "",
        "Una fitxa de matrimoni dona els pares i els quatre avis de la persona buscada,",
        "i els llibres de matrimonis solen tenir menys forats que els de bateigs. Per a",
        "tot el que caiga en un forat dels bateigs, doncs, **el camí és el matrimoni**,",
        "llevat que el llibre de matrimonis d'aquells anys sigui dels perduts.",
        "",
        "El que no arregla res d'això és el que va per damunt d'on comencen els llibres:",
        "això no es comprova ací, i es demana a l'arxiu que els custodia.",
        "",
        "La cobertura de cada parròquia, tal com la porta `tools.apv.coverage`:",
        "",
    ]
    for parish, spans in sorted(coverage.COVERAGE.items()):
        detail = ", ".join(
            f"{sacrament} {span}" for sacrament, span in sorted(spans.items())
        ) if isinstance(spans, dict) else str(spans)
        lines.append(f"- **{parish}** — {detail}")
    lines.append("")
    return "\n".join(lines)


def ancestors_by_sosa(tree: Tree, root: str | None = None) -> list[tuple[int, object]]:
    """Every ancestor with its Sosa number, lowest first.

    Walks `FAMC` rather than reading `_SOSADABOVILLE`: Ancestris labels a person
    with their *lowest* Sosa only, so anyone standing in two boxes of an implex
    carries one number and the count comes out short. Here each box is walked,
    and a person reached twice keeps the lowest number -- which is what an
    ordered worklist wants anyway.
    """
    root = root or root_person(tree)
    if not root:
        return []
    lowest: dict[str, int] = {}
    frontier = [(root, 1)]
    while frontier:
        nxt = []
        for xref, sosa in frontier:
            if xref in lowest and lowest[xref] <= sosa:
                continue
            lowest[xref] = min(sosa, lowest.get(xref, sosa))
            for parent in tree.parents(xref):
                offset = 0 if (parent.sex or "M") == "M" else 1
                nxt.append((parent.xref, sosa * 2 + offset))
        frontier = nxt
    pairs = [
        (sosa, tree.people[xref]) for xref, sosa in lowest.items() if xref in tree.people
    ]
    pairs.sort(key=lambda pair: pair[0])
    return pairs


def _archive_sources(tree: Tree, xref: str) -> set[str]:
    rec = tree.ged.by_xref.get(xref)
    if rec is None:
        return set()
    return {
        line.raw.strip().split()[-1].strip("@")
        for line in tree.ged.lines[rec.start : rec.end]
        if line is not None and line.raw.strip().startswith("1 SOUR ")
    } & config.apv_archive_sources()


def already_transcribed(root_dir: Path = ROOT) -> set[str]:
    """Everyone named in a transcription under an archive folder of `Fonts/`.

    The GEDCOM alone is not enough to answer "have we looked this person up?".
    On 01-08-2026 the plan sent a query for the Sosa 16's baptism and it came
    back empty -- because the fiche had been transcribed days earlier and the
    citation had been hung on the person searched for, not on everyone the fiche
    names. That is the `correccions-28` mistake, and it cost one of the day's
    fifteen.

    So the check is made against the transcriptions themselves, which cannot
    drift out of step with what was actually asked of the archive. The GEDCOM
    was repaired too, with `correccions-36`, but this no longer depends on it.

    **A transcription can name somebody in order to DENY them**, and that must
    not count. A good write-up says which people the fiche failed to establish,
    and reading those mentions as evidence turns an honest note into a hidden
    ancestor. Per file, `<!-- apv:no-documenta I00161 I00162 -->` subtracts them
    again. Found the same day this docstring was extended: the 1823 marriage
    write-up removed three ancestors from the plan by listing the three the
    fiche did not confirm.
    """
    found: set[str] = set()
    for folder in config.apv_archive_folders():
        for path in (root_dir / "Fonts" / folder).glob("*.md"):
            if path.name.startswith(("00 LLEGIU", "00 PLA")):
                continue
            text = path.read_text(encoding="utf-8")
            named = set(_XREF_IN_TEXT.findall(text))
            for denial in _NOT_DOCUMENTED.findall(text):
                named -= set(re.findall(r"I\d+", denial))
            found |= named
    return found


def _fold(text: str) -> str:
    """Lowercase and strip accents, so «Sarrió» and `sarrio` compare equal."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def fingerprint(lookup: Lookup) -> dict:
    """What identifies a search, so the same one is recognisable tomorrow.

    Deliberately NOT the prose of the log entry. The first version of this
    filter matched log text word by word and got eight false positives out of
    eleven, the worst being a Sosa 576 baptism dropped because a note about an
    unrelated search happened to contain the name of the same parish.
    Prose describing a search is not the search.

    The couple is stored as an **unordered pair**, which is the other thing that
    has to be right: the plan proposes one marriage once per spouse -- Sosa 148
    and 149 are the same document, and so are 288 and 289 -- and one query
    answers both.
    """
    terms = lookup.terms or {}
    a1, spouse = _fold(terms.get("a1", "")), _fold(terms.get("cognomcj", ""))
    return {
        "sacrament": _fold(lookup.sacrament),
        "parish": _fold(lookup.parish),
        # Only a two-sided search has a couple. A baptism must leave this empty
        # so the comparison falls through to a1 + a2 -- with one name in here it
        # never matched anything, which is how the Sosa 144's baptism survived
        # the first cut of this filter after already coming back empty.
        "couple": sorted([a1, spouse]) if (a1 and spouse) else [],
        "a1": a1,
        "a2": _fold(terms.get("a2", "")),
        # The window the URL actually carries, put there by `plan()` -- ±8 years
        # for a marriage and ±2 for a baptism. Recomputing it here would be a
        # second source of truth for the one number this comparison hinges on.
        "from": terms.get("from"),
        "to": terms.get("to"),
    }


def asked_before(path: Path | None = None) -> list[dict]:
    """Every search already made, from the query log's structured half.

    `already_transcribed` catches the searches that FOUND something, because a
    hit leaves a `.md` behind. **A search that comes back empty leaves nothing**,
    so it stayed in the plan for ever and got proposed again tomorrow.

    That is not hypothetical. On 03-08-2026 the regenerated plan re-proposed
    three searches from a few hours earlier -- one baptism and two marriages --
    all three of which had already come back with zero results. Three of the
    first eleven items. The log knew; the plan did not read it.

    A zero is a finding, not a blank: a baptism that is absent from the parish
    the plan assumed is evidence the person was born in another one, and that
    is only worth something if we stop paying for it twice.

    Entries with no `search` key are skipped, not guessed at: `--record` takes
    free prose and prose cannot be matched safely. Use `--asked N` to record a
    browser search against a numbered plan item, which stores the terms.
    """
    quota_file = path or (ROOT / "cache" / "apv-quota.json")
    if not quota_file.exists():
        return []
    try:
        state = json.loads(quota_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [e["search"] for e in (state.get("log") or []) if e.get("search")]


def _overlap(a: dict, b: dict) -> bool:
    """Do the two year windows meet? Unknown years never match anything."""
    if None in (a.get("from"), a.get("to"), b.get("from"), b.get("to")):
        return False
    return a["from"] <= b["to"] and b["from"] <= a["to"]


def _matches_a_past_search(lookup: Lookup, searches: list[dict]) -> dict | None:
    """The past search that already covers this lookup, if there is one.

    Same sacrament, same parish, same people, and year windows that meet. For a
    baptism «same people» means both surnames, because a1 alone would drop every
    cousin in a town where half the parish shares two surnames. For a marriage it
    means the unordered pair of the two first surnames.
    """
    mine = fingerprint(lookup)
    for past in searches:
        if mine["sacrament"] != past.get("sacrament"):
            continue
        if mine["parish"] != past.get("parish"):
            continue
        if not _overlap(mine, past):
            continue
        if mine["couple"]:
            if mine["couple"] == past.get("couple"):
                return past
        elif mine["a1"] == past.get("a1") and mine["a2"] == past.get("a2"):
            return past
    return None


def undocumented_ancestors(tree: Tree, root: str | None = None) -> list[tuple[int, object]]:
    """Ancestors whose ASCENDENCY is still open, lowest Sosa first.

    Sosa 1 is the root person themselves, who needs no verifying, and the living
    generations are barred by the index's embargo anyway -- but they are left in
    rather than filtered by age, because `coverage.covers` already refuses them
    with a reason worth reading, and a silent skip would hide people the index
    might reach sooner than expected.

    **A citation is not the same as an exhausted line, and conflating the two hid
    nineteen ancestors.** Found on 03-08-2026 by asking what had become of one
    surname: a Sosa 80 with no parents and no birth date was not being proposed
    at all -- because four fiches of his grandchildren name him. They name him
    **as a grandfather**, and the grandparent columns of this index give a name
    and nothing above it.

    So a document proves he existed and says nothing about where he came from.
    The other eighteen were the same shape, and they were SHALLOW: Sosa 44, 45,
    65, 66, 67, 73, 80, 83, 84, 92, 93 -- the sixth and seventh generations,
    while the plan busied itself with Sosa 145 and up.

    The rule that replaces it: **somebody with no parents in the tree is never
    finished.** Being documented only retires an ancestor once their filiation is
    actually in the file; until then there is, by definition, something left to
    ask. People the index cannot reach still appear and are refused by
    `coverage.covers` with a reason, which is the behaviour that was wanted all
    along.
    """
    transcribed = already_transcribed()
    out = []
    for sosa, person in ancestors_by_sosa(tree, root):
        if sosa <= 1 or not in_index_area(sosa):
            continue
        documented = bool(_archive_sources(tree, person.xref)) or person.xref in transcribed
        # The frontier is where the tree stops, not where the citations stop.
        if documented and tree.parents(person.xref):
            continue
        out.append((sosa, person))
    return out


def _label(person) -> str:
    sosa = f", Sosa {person.sosa.split()[0]}" if person.sosa else ""
    year = person.birth_year or "?"
    return f"{person.given} {person.surname} ({year}{sosa}) @{person.xref}@"


# ---------------------------------------------------------------------------
# Which archive holds a given ancestor, decided by BRANCH and not by birthplace
# ---------------------------------------------------------------------------
#
# Most families can say this in one sentence: everyone above one grandparent is
# from here, everyone above another is from there, except one branch that came
# from somewhere else. That sentence is the whole rule, and it beats reading
# birth places one by one.
#
# It works because Sosa numbering already encodes the branch. Halving a Sosa
# number walks down one generation, so repeatedly halving any ancestor lands on
# the person whose side they are on:
#
#     Sosa  2  the father's side       -> one region
#     Sosa  3  the mother's side       -> another
#     Sosa 11  a branch inside Sosa 2  -> a third (checked FIRST, it is inside 2)
#
# Order is why `apv: branques:` is a list and not a mapping: the narrowest
# branch has to be tested before the wider one that contains it.
#
# Reading places instead is what produced three of the four bugs of 01-08-2026:
# a fallback parish that sent four ancestors from one diocese to another, and a
# man with no place at all, no parents and no spouse with one. The branch rule
# answers all of those without looking at a single PLAC.
#
# One caveat worth stating: if the implex foci sit in different regions, a
# person standing in two boxes can land on two regions, and the first branch
# listed wins. Where they share a region -- the usual case -- it cannot happen.

# The branch roots are `apv: branques:` in config.yaml, and which of those
# regions this index actually holds is `apv: regions_amb_index:`. The other
# regions have their own archives and their own tooling.


def descends_from(sosa: int, ancestor: int) -> bool:
    """Whether the Sosa `ancestor` is on the path from `sosa` down to the root."""
    while sosa > ancestor:
        sosa //= 2
    return sosa == ancestor


def region_of(sosa: int) -> str | None:
    """Which family branch a Sosa number belongs to. None for the root herself."""
    for root, name in config.apv_branches():
        if descends_from(sosa, root):
            return name
    return None


def in_index_area(sosa: int) -> bool:
    """Whether this ancestor could be in the index's area at all.

    With no branches configured there is no rule to apply, and everybody stays
    in: planning nothing at all is the one answer that is never useful.
    """
    regions = config.apv_index_regions()
    if not regions or not config.apv_branches():
        return True
    return region_of(sosa) in regions


def _parish_of(person, tree: Tree) -> str:
    """Where the sacrament would have been recorded.

    Careful: **a birth place is not a parish**, and the two diverge on purpose.
    A hamlet with no church of its own has its baptisms in the mother parish's
    books until the year it got its own, so the rules in `apv: parroquies:` can
    redirect by year. Getting this wrong searches the wrong books and reports a
    real record as missing.

    When the person's own place says nothing, the places of the people around
    them usually do: a spouse or a parent born in the parish is good enough to
    aim a query that would otherwise not happen at all.
    """
    rules = config.apv_parish_rules()
    year = person.birth_year

    def match(place: str) -> str | None:
        text = (place or "").lower()
        if not text:
            return None
        for rule in rules:
            needles = rule.get("si_el_lloc_conte") or []
            if isinstance(needles, str):
                needles = [needles]
            if not any(str(n).lower() in text for n in needles):
                continue
            before = rule.get("abans_de")
            if before and year and year < int(before):
                return str(rule.get("llavors") or rule.get("parroquia", ""))
            return str(rule.get("parroquia", ""))
        return None

    found = match(person.birth_place)
    if found:
        return found

    # Any other parish the index covers, when the birth place names it. Without
    # this the fallback below reaches for a spouse's parish instead, and on
    # 31-07-2026 that would have spent a query looking for a woman born in a
    # town the index covers 1564-1915 in her husband's parish instead. The
    # wrong parish does not come back empty-handed with an explanation; it just
    # comes back empty.
    place = (person.birth_place or "").lower()
    for key in coverage.COVERAGE:
        if key in place:
            return key

    for other in tree.spouses(person.xref) + tree.parents(person.xref):
        found = match(other.birth_place)
        if found:
            return found
    return config.apv_default_parish()


# Both of the numbers this file estimates with vary by place and period, so
# they are settings: `apv: edat_de_casar:` and `apv: anys_per_generacio:`.


def _birth_year_estimate(person, tree: Tree | None = None) -> tuple[int | None, int]:
    """A birth year even when the record has none, by looking DOWN the tree.

    Returns `(year, hops)`; hops 0 means the year is the person's own.

    **Looking down is what unblocks these people, and it is not obvious**: the
    same move fixed the parish fallback on 03-08-2026 (walk up and there is
    nothing; the generation below always has something) and it was never applied
    to dates. The Sosa 80, Josep Biosca Pascual, has no birth date and neither
    does his son, so the plan could not date him at all and refused both his
    baptism and his marriage with «sense any no es pot apuntar». His GRANDSON was
    born 8 JUL 1900, which puts him around 1840 -- inside his parish's baptism
    coverage.

    **The estimate leans late, and the caller has to pay for that with a wider
    window.** This tree holds only ancestors, so the one recorded child of a
    couple is whichever one we descend from and rarely the firstborn -- the same
    trap `_marriage_year` documents. Anchoring on them makes the parent look
    younger than they were, so the real birth is usually EARLIER than what comes
    out of here. `hops` is returned precisely so the window can widen with the
    guessing.
    """
    if person.birth_year:
        return person.birth_year, 0
    if tree is None:
        return None, 0
    seen = {person.xref}
    frontier = [person.xref]
    for hops in range(1, 4):
        nxt, years = [], []
        for xref in frontier:
            for child in tree.children(xref):
                if child.xref in seen:
                    continue
                seen.add(child.xref)
                if child.birth_year:
                    years.append(child.birth_year)
                nxt.append(child.xref)
        if years:
            return min(years) - config.generation_years() * hops, hops
        if not nxt:
            break
        frontier = nxt
    return None, 0


def _marriage_year(person, spouse, tree: Tree | None = None) -> int | None:
    """No MARR events in this branch, so estimate. Carefully.

    The resum gives marriage ages in prose, not as dates, and tools.apply does
    not write MARR, so this has to be inferred.

    **The trap, and it bit on the first run**: the obvious anchor is the eldest
    known child, but THIS TREE ONLY HOLDS ANCESTORS. The one child recorded for
    a couple is whichever one we descend from, and that is rarely the firstborn.
    Anchoring on it put one ancestor's wedding at 1789 when a family summary
    says 1767 -- twenty-two years late, because his seven siblings are not in
    the file and the one we descend from is the fourth of them.

    Twenty-two years is not a harmless error. In a parish whose marriages run,
    say, 1784-1803 and 1849-1914, that size of drift flips the verdict from
    "covered" to "gap" and wastes a query, or worse, skips a possible one.

    So: birth + `apv: edat_de_casar:` as the estimate, and the eldest recorded
    child only as a
    **ceiling** -- they certainly married before that child was born.
    """
    child_years = [
        c.birth_year for c in (tree.children(person.xref) if tree else []) if c.birth_year
    ]
    ceiling = min(child_years) - 1 if child_years else None

    from_age = None
    if person.birth_year:
        from_age = person.birth_year + config.marriage_age()
    elif spouse is not None and spouse.birth_year:
        from_age = spouse.birth_year + config.marriage_age() - 2
    else:
        # Neither has a recorded birth. Estimate from a dated descendant rather
        # than giving up: refusing outright is what hid the Biosca line.
        estimate, _ = _birth_year_estimate(person, tree)
        if estimate is None and spouse is not None:
            estimate, _ = _birth_year_estimate(spouse, tree)
        if estimate is not None:
            from_age = estimate + config.marriage_age()

    if from_age is not None and ceiling is not None:
        return min(from_age, ceiling)
    return from_age if from_age is not None else ceiling


def _first(surname: str) -> str:
    return (surname or "").split()[0] if surname else ""


def _second(surname: str) -> str:
    """The second surname, skipping the Catalan «i» that joins the two.

    Half this tree writes «MITJAVILA I GELI» and the other half «MICÓ REVERT».
    Without this the plan sent `a2=i` for every Catalan name -- four queries that
    would have searched the index for people whose surname is the conjunction.
    """
    parts = [p for p in (surname or "").split() if p.lower() not in ("i", "y")]
    return parts[1] if len(parts) > 1 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--gedcom", default=None)
    parser.add_argument("--top", type=int, default=0,
                        help="amb --fetch, quantes consultes fer com a màxim")
    parser.add_argument("--fetch", action="store_true",
                        help="demana de veres les primeres --top consultes")
    parser.add_argument("--asked", metavar="N:QUÈ", action="append", default=[],
                        help="apunta que has fet al navegador la consulta número N "
                             "del pla, amb el que n'ha sortit després dels dos punts. "
                             "A diferència de --record, desa els TERMES de la cerca, "
                             "i per això el pla no la tornarà a proposar ni que haja "
                             "tornat buida. Repetible: --asked 3:0 resultats")
    args = parser.parse_args()

    session = build_session(args)
    for what in getattr(args, "record", []) or []:
        session.quota.spend(f"[navegador] {what}")
        print(f"apuntada: {what}")

    if args.asked:
        # Resolving N needs the plan, so this runs before the report is written
        # and the report below is regenerated with these searches already out.
        current = [l for l in plan(Tree(args.gedcom or tree_path())) if l.possible]
        for entry in args.asked:
            num, _, outcome = entry.partition(":")
            try:
                lookup = current[int(num.strip()) - 1]
            except (ValueError, IndexError):
                print(f"  no hi ha cap número {num.strip()!r} al pla d'ara; no s'apunta")
                continue
            session.quota.spend(
                f"[navegador] {lookup.sacrament} {lookup.who} {lookup.parish} — "
                f"{outcome.strip() or 'sense anotar'}",
                search=fingerprint(lookup),
            )
            print(f"apuntada la {num.strip()}: {lookup.who} — {outcome.strip()}")

    if args.quota or ((getattr(args, "record", []) or args.asked) and not args.fetch):
        tree = Tree(args.gedcom or tree_path())
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(render(plan(tree), session.quota.summary()), encoding="utf-8")
        print(session.quota.summary())
        return 0

    tree = Tree(args.gedcom or tree_path())
    lookups = plan(tree)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(lookups, session.quota.summary()), encoding="utf-8")
    doable = [l for l in lookups if l.possible]
    print(f"{len(lookups)} comprovacions, {len(doable)} demanables -> {REPORT.relative_to(ROOT)}")
    print(session.quota.summary())

    if not args.fetch:
        print("cap petició feta. Passa --fetch --top N per demanar-ne unes quantes.")
        return 0

    budget = min(args.top or 0, session.quota.remaining())
    if budget <= 0:
        print("res a demanar: o --top és 0 o no queden consultes avui.")
        return 0

    from .parse import parse_results, quota_line

    for l in doable[:budget]:
        print(f"\n-> {l.who}: {l.sacrament} {l.year}, {l.parish}")
        try:
            page = session.get(l.url, why=f"{l.xref} {l.sacrament} {l.year}")
        except QuotaExhausted as exc:
            print(f"  ATURAT: {exc}")
            break
        except Challenged as exc:
            print(f"  ATURAT: {exc}")
            print("\n  Les URL són al report; obri-les al navegador i desa la pàgina.")
            print("  Després: parse.parse_fiche(html) i parse.to_markdown(...).")
            break
        if not page:
            continue
        note = quota_line(page)
        if note:
            print(f"  l'arxiu diu: {note}")
        hits = parse_results(page)
        print(f"  {len(hits)} referència(es)")
        for h in hits[:6]:
            print(f"    · {h['book']} ({h['from']}-{h['to']}) foli {h['folio']} {h.get('registro','')}")
    print(f"\n{session.stats()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

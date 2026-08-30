"""Turn the research frontier into reviewable proposals.

For each dead-end in the canonical tree, work out what can be added and write it
to a YAML file for review. Nothing touches the GEDCOM: that is tools/apply.py,
and only for entries marked `accept: true`.

Two kinds of proposal come out:

  parents   FamilySearch already records this person's parents. The proposal
            carries both parents, everything above them that is new, and a
            confidence based on whether we can corroborate it independently.
  records   Nobody knows the parents. The proposal carries candidate historical
            records (baptisms, marriages) found by searching the parish, for a
            human to read and judge.

    python3 -m tools.research --top 5
    python3 -m tools.research --target I00044 --depth 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from .config import tree_path
from .frontier import (
    SNAPSHOT,
    FrontierEntry,
    build,
    documents_for,
    index_documents,
    snapshot_load,
)
from .fs.api import Api
from .fs.fetch import LiveTree
from .fs.session import add_common_args, build_session
from .normalize import place_key
from .people import Person, Tree

from .config import ROOT
PEDIGREE = ROOT / "cache" / "pedigree.json"
REPORTS = ROOT / "reports"
FS_PERSON = "https://www.familysearch.org/tree/person/details/"


def person_block(p: Person, documents: list[str] | None = None) -> dict:
    """One person as YAML, in the shape tools/apply.py expects."""
    block = {
        "given": p.given,
        "surname": p.surname,
        "sex": p.sex,
        "birth_date": p.birth_date,
        "birth_place": p.birth_place,
        "death_date": p.death_date,
        "death_place": p.death_place,
        "fsftid": p.xref,
        "familysearch": f"{FS_PERSON}{p.xref}",
    }
    if documents:
        block["documents"] = documents
    return {k: v for k, v in block.items() if v not in (None, "", [])}


def upstream_chain(
    live: LiveTree, start: list[str], known: set[str], depth: int
) -> list[list[Person]]:
    """Ancestors above `start`, level by level, excluding people already in the tree."""
    levels: list[list[Person]] = []
    frontier, seen = list(start), set(known)
    for _ in range(depth):
        nxt: list[Person] = []
        for person in frontier:
            for parent in live.parents(person):
                if parent.xref in seen:
                    continue
                seen.add(parent.xref)
                nxt.append(parent)
        if not nxt:
            break
        levels.append(nxt)
        frontier = [p.xref for p in nxt]
    return levels


CITATIONS_SHOWN = 6


def pick_citations(cites: list[dict], shared: set[str], limit: int = CITATIONS_SHOWN) -> list[dict]:
    """The documents worth printing, the corroborating ones first.

    A well-worked person can carry fifty attached sources and printing them all
    would bury the proposal in the noise it is supposed to cut through. The ones
    that also hang on the target go first and are flagged, because those are the
    ones that decide anything.
    """
    marked = [
        {**c, "shared_with_target": True} if c.get("url") in shared else c
        for c in cites
    ]
    marked.sort(key=lambda c: not c.get("shared_with_target"))
    return marked[:limit]


def corroborating_documents(
    api: "Api | None", target_pid: str | None, parents: list[Person]
) -> tuple[dict[str, list[dict]], dict[str, set[str]]]:
    """What FamilySearch cites for each proposed parent, and what it shares with the target.

    The shared part is the whole reason for the call. A document attached to the
    child *and* to the parent is FamilySearch saying one record covers them both
    -- a baptism that names the father, most of the time -- and that is evidence
    about the link itself, not about how carefully somebody typed.

    Costs one request per person and they are all cached, so a re-run is free.
    Ancestors above the parents are deliberately not asked about: it would
    multiply the requests by the depth to corroborate links nobody is being
    asked to accept yet.
    """
    if api is None or not target_pid:
        return {}, {}
    target_urls = {c["url"] for c in api.citations(target_pid) if c.get("url")}
    cites = {q.xref: api.citations(q.xref) for q in parents}
    shared = {
        pid: {c["url"] for c in found if c.get("url") in target_urls}
        for pid, found in cites.items()
    }
    return cites, shared


def propose_parents(
    entry: FrontierEntry,
    live: LiveTree,
    known: set[str],
    depth: int,
    docs: dict,
    api: "Api | None" = None,
    contributors: bool = True,
    citations: bool = True,
) -> dict:
    p = entry.person
    parents = entry.fs_parents

    # Who entered this on FamilySearch matters more than how tidy it looks. It is
    # a shared tree: a relationship a stranger added is a claim to be checked,
    # while one the user added himself is his own research, already cross-checked
    # against relatives and registers. So his own data is trusted by default.
    mine: list[str] = []
    editors: dict[str, list[str]] = {}
    if api is not None and contributors and api.fs.tree_user_id:
        for q in parents:
            who = api.contributors(q.xref)
            editors[q.xref] = sorted(set(who.values()))
            if api.fs.tree_user_id in who:
                mine.append(q.xref)

    cited, shared = corroborating_documents(
        api if citations else None, p.fsftid, parents
    )
    corroborated = [pid for pid, urls in shared.items() if urls]

    # Confidence is about the *link*, not about FamilySearch being tidy. A
    # certificate of our own naming the parent is the strongest evidence here.
    if mine and len(mine) == len(parents):
        confidence = "high"
        why = "ho vas entrar tu mateix a FamilySearch"
    elif entry.parent_documents:
        confidence = "high"
        why = "un document nostre anomena el progenitor proposat"
    elif corroborated:
        # The case this rule was written for: I00514 Antonio Valiente came out
        # `low` -- «poques dades, entrades per altri» -- while the 1786 baptism
        # that names him and his father in the same line was attached to both of
        # them all along. Reading a citation is not trusting a stranger's typing.
        confidence = "high"
        why = (
            "un mateix document de FamilySearch anomena el target i "
            + ("tots dos progenitors" if len(corroborated) == len(parents) == 2
               else "el progenitor proposat" if len(corroborated) == 1 == len(parents)
               else f"{len(corroborated)} de {len(parents)} progenitors")
        )
    elif mine:
        confidence = "medium"
        why = f"{len(mine)} de {len(parents)} progenitors els vas entrar tu a FamilySearch"
    elif len(parents) == 2 and all(q.birth_date for q in parents):
        confidence = "medium"
        why = "FamilySearch té els dos progenitors amb dates, entrats per altri"
    else:
        confidence = "low"
        why = "FamilySearch té el parentiu però amb poques dades, entrades per altri"

    proposal = {
        "kind": "parents",
        "target": p.xref,
        "target_name": f"{p.given} {p.surname}",
        "target_birth": p.birth_date or None,
        "target_place": p.birth_town or None,
        "confidence": confidence,
        "why": why,
        "source_url": f"{FS_PERSON}{p.fsftid}",
        "parents": [
            {
                **person_block(q, entry.parent_documents.get(q.xref)),
                **({"editors": editors[q.xref]} if q.xref in editors else {}),
                **({"entrat_per_tu": True} if q.xref in mine else {}),
                **(
                    {"citations": pick_citations(cited[q.xref], shared.get(q.xref, set()))}
                    if cited.get(q.xref)
                    else {}
                ),
            }
            for q in parents
        ],
        # Data the user entered himself is accepted by default; anybody else's is
        # left for him to look at.
        "accept": True if (mine and len(mine) == len(parents)) else None,
    }

    if depth > 1:
        starting = [q.xref for q in parents]
        levels = upstream_chain(live, starting, known | set(starting), depth - 1)
        if levels:
            proposal["ancestors"] = [
                [person_block(q) for q in level] for level in levels
            ]
            proposal["ancestors_note"] = (
                f"{sum(len(l) for l in levels)} avantpassats més amunt, per "
                f"generacions. S'importen només si accept_ancestors és cert."
            )
            proposal["accept_ancestors"] = None
    return {k: v for k, v in proposal.items() if v is not None or k in ("accept", "accept_ancestors")}


def search_records(api: Api, person: Person, limit: int = 8) -> list[dict]:
    """Historical records that might identify this person's parents."""
    parts = person.surname_parts
    if not parts:
        return []
    terms: dict[str, str] = {"surname": person.surname}
    if person.given:
        terms["given_name"] = person.given.split(",")[0].split()[0]
    if person.birth_place:
        terms["birth_like_place"] = person.birth_place
    if person.birth_year:
        terms["birth_like_date"] = str(person.birth_year)

    data = api.records_search(count=limit, **terms)
    if not data:
        return []
    out = []
    for entry in data.get("entries") or ():
        content = ((entry.get("content") or {}).get("gedcomx") or {})
        people = content.get("persons") or []
        if not people:
            continue
        principal = next((q for q in people if q.get("principal")), people[0])
        display = principal.get("display") or {}
        # Parents named in the record are the whole point of looking.
        relatives = [
            (q.get("display") or {}).get("name")
            for q in people
            if q is not principal
        ]
        out.append(
            {
                k: v
                for k, v in {
                    "record": entry.get("title"),
                    "name": display.get("name"),
                    "birth": display.get("birthDate"),
                    "place": display.get("birthPlace"),
                    "others_named": [r for r in relatives if r][:6],
                    "url": (entry.get("id") or "").replace(
                        "https://familysearch.org/ark:", "https://www.familysearch.org/ark:"
                    ),
                }.items()
                if v
            }
        )
    return out


def propose_records(entry: FrontierEntry, api: Api, docs: dict) -> dict | None:
    p = entry.person
    hits = search_records(api, p)
    if not hits:
        return None
    return {
        "kind": "records",
        "target": p.xref,
        "target_name": f"{p.given} {p.surname}",
        "target_birth": p.birth_date,
        "target_place": p.birth_town,
        "confidence": "unverified",
        "why": (
            "candidats de la cerca de registres històrics. Cal llegir-los: la "
            "cerca no comprova res, només proposa."
        ),
        "archive": entry.archive or None,
        "candidates": hits,
        "accept": None,
    }


def previously_rejected(reports: Path) -> dict[str, str]:
    """Targets already marked `accept: false` in an earlier review file.

    Without this, a proposal refuted by an actual parish record comes back on the
    next run looking respectable, and might be accepted by mistake the second
    time. A rejection is a decision and has to survive.

    `tools.archive` moves decided `accept: false` entries out of
    `reports/candidates-*.yaml` into `reports/descartades/candidates-*.yaml`
    once they've been read here, so both places are scanned.
    """
    out: dict[str, str] = {}
    for folder in (reports, reports / "descartades"):
        for path in sorted(folder.glob("candidates-*.yaml")):
            try:
                entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            except yaml.YAMLError:
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("accept") is False:
                    out[str(entry.get("target", "")).strip("@")] = path.name
    return out


def already_proposed(reports: Path) -> dict[str, str]:
    """Targets with a proposal still waiting on a decision in an open
    `reports/candidates-*.yaml`.

    `previously_rejected` keeps a `false` from coming back; this keeps a
    still-undecided `null` from coming back too. Without it, a target
    proposed yesterday and not yet reviewed gets a second, identical-looking
    proposal in today's file instead of waiting for a decision on the first
    one -- which is what happened before this existed: the same three
    candidates, verbatim, in `candidates-2026-08-28.yaml` and
    `candidates-2026-08-29.yaml` alike.
    """
    out: dict[str, str] = {}
    for path in sorted(reports.glob("candidates-*.yaml")):
        try:
            entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        except yaml.YAMLError:
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("accept") is None:
                out[str(entry.get("target", "")).strip("@")] = path.name
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--pedigree", default=PEDIGREE)
    parser.add_argument("--target", help="one person, by xref")
    parser.add_argument("--top", type=int, default=5, help="how many frontier people [5]")
    parser.add_argument(
        "--depth",
        type=int,
        default=1,
        help="how many generations above the parents to propose [1 = parents only]",
    )
    parser.add_argument(
        "--no-contributors",
        action="store_true",
        help="skip looking up who edited each person on FamilySearch "
        "(with --no-citations too, the run needs no session at all)",
    )
    parser.add_argument(
        "--no-citations",
        action="store_true",
        help="skip reading the documents FamilySearch cites for each person "
        "(one cached request per person; they are what corroborates a link)",
    )
    parser.add_argument(
        "--search",
        action="store_true",
        help="also search historical records for people FamilySearch cannot help with "
        "(costs requests)",
    )
    parser.add_argument(
        "--status",
        choices=("ready", "stuck", "unlinked"),
        help="only frontier people in this state",
    )
    parser.add_argument("--out", help="output YAML [reports/candidates-<today>.yaml]")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite an existing output file instead of numbering a new one",
    )
    args = parser.parse_args()

    canon = Tree(args.canonical or tree_path())
    path = Path(args.pedigree)
    snapshot = None
    if path.exists():
        live = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))
    else:
        # No credentials fetched today: fall back to the committed snapshot of
        # already-known parents, same as tools.frontier does without a live
        # pedigree. It only carries direct parents, not the grandparents a
        # deeper proposal would need, so depth is capped at 1 here.
        live = None
        snapshot = snapshot_load(SNAPSHOT)
        if snapshot is None:
            print(
                f"no pedigree at {path} and no snapshot at {SNAPSHOT}; "
                "run tools.fs.fetch first",
                file=sys.stderr,
            )
            return 2
        print(f"no pedigree at {path}; working from {SNAPSHOT} instead", file=sys.stderr)
        if args.depth > 1:
            print("  (snapshot has no ancestors above the parents; using --depth 1)", file=sys.stderr)
            args.depth = 1
    entries = build(canon, live, snapshot)
    docs = index_documents()
    known = {p.fsftid for p in canon.people.values() if p.fsftid}

    if args.target:
        wanted = args.target.strip("@")
        entries = [e for e in entries if e.person.xref == wanted]
        if not entries:
            print(f"@{wanted}@ is not on the frontier (it may already have parents)")
            return 1
    else:
        if args.status:
            entries = [e for e in entries if e.status == args.status]
        entries = entries[: args.top]

    rejected = previously_rejected(REPORTS)
    skipped = [e for e in entries if e.person.xref in rejected]
    for e in skipped:
        print(
            f"  descartada abans  @{e.person.xref}@ {e.person.given} "
            f"{e.person.surname} (a {rejected[e.person.xref]})"
        )
    entries = [e for e in entries if e.person.xref not in rejected]

    pending = already_proposed(REPORTS)
    waiting = [e for e in entries if e.person.xref in pending]
    for e in waiting:
        print(
            f"  ja proposada  @{e.person.xref}@ {e.person.given} "
            f"{e.person.surname}: pendent de decisió a {pending[e.person.xref]}"
        )
    entries = [e for e in entries if e.person.xref not in pending]

    proposals: list[dict] = []
    api = None
    for entry in entries:
        if entry.status == "ready":
            if api is None and not (args.no_contributors and args.no_citations):
                api = Api(build_session(args))
            proposals.append(
                propose_parents(
                    entry, live, known, args.depth, docs, api,
                    contributors=not args.no_contributors,
                    citations=not args.no_citations,
                )
            )
            print(
                f"  parents  @{entry.person.xref}@ {entry.person.given} "
                f"{entry.person.surname}: {len(entry.fs_parents)} progenitors"
                + (f", +{entry.upstream} amunt" if entry.upstream else "")
            )
        elif args.search:
            if api is None:
                api = Api(build_session(args))
            proposal = propose_records(entry, api, docs)
            if proposal:
                proposals.append(proposal)
                print(
                    f"  records  @{entry.person.xref}@ {entry.person.given} "
                    f"{entry.person.surname}: {len(proposal['candidates'])} candidats"
                )
            else:
                print(
                    f"  cap res  @{entry.person.xref}@ {entry.person.given} "
                    f"{entry.person.surname}: la cerca no torna res"
                )
        else:
            print(
                f"  omesa    @{entry.person.xref}@ {entry.person.given} "
                f"{entry.person.surname} ({entry.status}) — cal --search"
            )

    if not proposals:
        print("\nno proposals")
        return 0

    REPORTS.mkdir(exist_ok=True)
    out = Path(args.out) if args.out else REPORTS / f"candidates-{date.today().isoformat()}.yaml"
    if not out.is_absolute():
        out = ROOT / out
    if out.exists() and not args.overwrite:
        # An existing file is the record of what was already reviewed and applied.
        # Clobbering it would erase that, so number a new one instead.
        stem, suffix = out.stem, out.suffix
        n = 2
        while (candidate := out.with_name(f"{stem}-{n}{suffix}")).exists():
            n += 1
        print(f"  {out.name} ja existeix; escric a {candidate.name}")
        out = candidate
    header = (
        "# Propostes de recerca. Res no toca el GEDCOM fins que ho acceptis aquí.\n"
        "#\n"
        f"# accept: true   -> s'incorpora a «{tree_path().name}»\n"
        "# accept: false  -> es descarta\n"
        "# accept: null   -> pendent (no es fa res)\n"
        "#\n"
        "# accept_ancestors: true incorpora també les generacions de més amunt.\n"
        "#\n"
        "# Comprova-ho amb reports/frontier.md al costat. Els candidats de tipus\n"
        "# «records» no estan verificats: la cerca proposa, no confirma.\n"
        "\n"
    )
    out.write_text(
        header + yaml.safe_dump(proposals, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"\nwrote {out.relative_to(ROOT)} ({len(proposals)} proposals)")
    if api is not None:
        print(api.fs.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())

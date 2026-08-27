"""Ask FamilySearch about the frontier people the pedigree never reached.

`tools.fs.fetch` walks the ancestry of one root, so it only ever answers for
people who sit *above* that root. Everyone else linked to FamilySearch -- a
collateral line, someone linked later by hand, an eighth-generation person the
chaining stopped at -- comes out of the fetch with no parent edges at all. That
is not the same as FamilySearch not knowing their parents, and `frontier.md`
counts them under **Sense comprovar** for exactly that reason: nobody asked.

This asks. One `ancestry` call per pending person, merged into the same
`cache/pedigree.json` the fetch wrote, in the order `frontier.md` itself ranks
them -- so a run that stops early has spent its requests on the people worth
the most. Afterwards every person it reached has a real answer, and the reports
built from that pedigree move them out of «Sense comprovar»: into **A punt
d'importar** when FamilySearch does know the parents, into **Encallades** when
it genuinely does not.

The lesson `tools/fs/probe.py` records applies here too: a check that is never
made against the right subject does not give a "no", it gives a "don't know"
dressed up as one.

    python3 -m tools.fs.check              # everyone still unanswered
    python3 -m tools.fs.check --limit 20   # just the top of the queue
    python3 -m tools.fs.check --dry-run    # who would be asked, no requests
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import frontier
from ..config import ROOT, tree_path
from ..people import Person, Tree
from .api import Api
from .fetch import LiveTree, _absorb
from .session import FamilySearchError, add_common_args, build_session

PEDIGREE = ROOT / "cache" / "pedigree.json"


def unanswered(live: LiveTree) -> set[str]:
    """PIDs the pedigree *contains* but holds no answer about.

    Being in the pedigree with no parent edge normally means FamilySearch was
    asked and does not know the parents either -- a real answer, and one worth
    not paying to hear twice. There is one exception: a person returned at the
    eighth generation of a call and then never re-rooted from, which
    `fetch_pedigree` records in `skipped_leaves`. Their parents would have been
    the ninth generation of that call, so they were never in the response to
    begin with. Empty for the same reason, but a question rather than an answer.

    The other silence -- a PID the fetch never returned at all -- cannot be
    enumerated from here, because nothing in the pedigree mentions it. It shows
    up in `pending()` as plain absence.
    """
    return set(live.skipped_leaves)


def pending(canon: Tree, live: LiveTree) -> list[Person]:
    """Frontier people linked to FamilySearch that the pedigree cannot answer for.

    Two ways to qualify: the pedigree never mentions the PID at all (a
    collateral line, a link made by hand, anything not above the fetch's root),
    or it mentions it without ever having asked about the parents (see
    `unanswered`). Everyone else already has an answer, negative ones included.

    Ordered the way `frontier.md` orders them, so `--limit` keeps the people
    worth the most rather than an arbitrary slice.
    """
    gaps = unanswered(live)
    out: list[Person] = []
    for entry in frontier.build(canon, live):
        pid = entry.person.fsftid
        if not pid:
            continue
        if pid not in live.people or pid in gaps:
            out.append(entry.person)
    return out


def check_person(api: Api, live: LiveTree, person: Person) -> int | None:
    """Ask for one person's ancestry and merge it in.

    Returns how many parents FamilySearch knows -- `0` being a real answer,
    "it is stuck here too" -- or `None` when the question could not be put at
    all, which is the one case that must never be read as a zero. Session.get
    returns nothing for a 403 or a 404, and a person who could not be asked
    stays pending for the next run rather than joining the stuck.

    One call, not the chained walk `fetch_pedigree` does: the question here is
    whether FamilySearch knows the parents, and eight generations above them is
    already far more than that question needs. Chaining deeper is what the next
    `tools.fs.fetch` is for, once these people are in the tree.
    """
    pid = person.fsftid
    if not pid:
        return None
    data = api.ancestry(pid, generations=8)
    live.calls += 1
    if not data:
        return None
    _absorb(live, data)
    # Answered now, whichever way it came out.
    if pid in live.skipped_leaves:
        live.skipped_leaves.remove(pid)
    return len(live.parents(pid))


def dedupe_couples(live: LiveTree) -> None:
    """Drop repeated couple pairs before writing.

    `_absorb` appends, and every call here overlaps the ones before it, so the
    same marriage arrives once per call that touched it. `spouses()` already
    tolerates that; the file on disk should not have to carry it.
    """
    seen, unique = set(), []
    for pair in live.couples:
        key = tuple(pair)
        if key not in seen:
            seen.add(key)
            unique.append(pair)
    live.couples = unique


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--pedigree", default=PEDIGREE,
                        help="the fetched pedigree to read and enrich")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="how many people to ask about, best-ranked first [0 = all pending]",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list who would be asked and exit, without logging in",
    )
    args = parser.parse_args()

    path = Path(args.pedigree)
    if not path.exists():
        print(
            f"no pedigree at {path}. Run `python -m tools.fs.fetch` first: this "
            "step enriches what the fetch brought back, it does not replace it.",
            file=sys.stderr,
        )
        return 1

    canon = Tree(args.canonical or tree_path())
    live = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))
    queue = pending(canon, live)
    if args.limit > 0:
        queue = queue[: args.limit]

    if not queue:
        print("res per comprovar: el pedigrí ja respon per tots els fronts enllaçats")
        return 0

    print(f"{len(queue)} persones per comprovar a FamilySearch")
    if args.dry_run:
        for person in queue:
            print(f"  {person.fsftid}  @{person.xref}@ {person.label()}")
        return 0

    try:
        fs = build_session(args)
    except FamilySearchError as exc:
        print(f"login failed:\n{exc}", file=sys.stderr)
        return 1
    api = Api(fs)

    ready = stuck = unreachable = asked = 0
    try:
        for person in queue:
            found = check_person(api, live, person)
            asked += 1
            if found is None:
                # Counting this as "FamilySearch is stuck here too" would be
                # the very thing this step exists to stop: it is not an
                # answer, it is a question that could not be put.
                unreachable += 1
                print(f"  ?       {person.fsftid} @{person.xref}@ no respon")
            elif found:
                ready += 1
                print(f"  pares   {person.fsftid} @{person.xref}@ {person.label()}")
            else:
                stuck += 1
    except FamilySearchError as exc:
        # Whatever was answered before the cap is real and worth keeping: the
        # reports are written from this file straight after, and losing it
        # would mean having spent the requests for nothing.
        print(f"\naturat: {exc}", file=sys.stderr)

    dedupe_couples(live)
    path.write_text(
        json.dumps(live.to_json(), ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(
        f"\n{asked} comprovades de {len(queue)}: {ready} amb pares a FamilySearch "
        f"(a punt d'importar), {stuck} encallades també allà"
        + (f", {unreachable} sense resposta" if unreachable else "")
    )
    left = len(queue) - asked + unreachable
    if left:
        print(f"{left} encara sense comprovar; torna-hi per acabar-les")
    print(f"{fs.stats()}")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

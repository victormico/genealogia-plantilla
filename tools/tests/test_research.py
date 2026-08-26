"""Regression test for `tools.research --depth`.

The bug it pins: `upstream_chain` used to start its walk from the *target*'s
own xref, whose parents were already in the `known` exclusion set (they are
the proposal's own `parents` block) -- so the very first hop always found
"nothing new" and stopped there, before ever reaching the grandparents. Any
`--depth` above 1 silently behaved like `--depth 1`: no `ancestors` section,
no matter how deep the live pedigree actually went. Found investigating
quatre avantpassats seguits (issue #45): `--depth 3` came back with parents only, four
times in a row, for people whose FamilySearch pedigree visibly continues
several generations further.

`LiveTree` Person objects have `xref == fsftid` (both are the FamilySearch
id, see `tools/fs/fetch.py::_person_from_json`), which the fixtures below
mirror -- using different values for the two would hide the bug instead of
pinning it.

    python3 -m tools.tests.test_research
"""

from __future__ import annotations

import sys

from .. import research
from ..fs.fetch import LiveTree
from ..people import Person


def _person(fsftid: str, given: str, surname: str) -> Person:
    return Person(
        xref=fsftid,
        name=f"{given} /{surname}/",
        given=given,
        surname=surname,
        sex=None,
        birth_date=None,
        birth_place=None,
        death_date=None,
        death_place=None,
        fsftid=fsftid,
        famc=None,
    )


def _three_generation_tree() -> LiveTree:
    """target <- (father, mother) <- (grandfather, grandmother) on the father's side."""
    target = _person("F-TARGET", "Target", "PERSON")
    father = _person("F-FATHER", "Father", "PERSON")
    mother = _person("F-MOTHER", "Mother", "PERSON")
    grandfather = _person("F-GRANDFATHER", "Grandfather", "PERSON")
    grandmother = _person("F-GRANDMOTHER", "Grandmother", "PERSON")
    return LiveTree(
        people={p.fsftid: p for p in (target, father, mother, grandfather, grandmother)},
        father_of={"F-TARGET": "F-FATHER", "F-FATHER": "F-GRANDFATHER"},
        mother_of={"F-TARGET": "F-MOTHER", "F-FATHER": "F-GRANDMOTHER"},
    )


def test_upstream_chain_reaches_past_the_parents() -> None:
    live = _three_generation_tree()
    parents = live.parents("F-TARGET")
    starting = [q.xref for q in parents]

    # depth=1: one level above the parents -> the grandparents on the father's side
    # (the mother's own parents are not modelled here, so only the father's side).
    levels = research.upstream_chain(live, starting, set(starting), 1)
    assert levels, "expected at least one level above the parents"
    found = {p.xref for level in levels for p in level}
    assert found == {"F-GRANDFATHER", "F-GRANDMOTHER"}, f"expected both grandparents, got {found}"


def test_upstream_chain_does_not_regress_to_always_empty() -> None:
    # The bug this test exists for: calling upstream_chain seeded from the
    # *target* itself, with the target's own parents pre-excluded, always
    # returned [] regardless of depth. Guard the buggy call shape directly.
    live = _three_generation_tree()
    parents = live.parents("F-TARGET")
    known_with_parents_excluded = {q.xref for q in parents}
    buggy = research.upstream_chain(live, ["F-TARGET"], known_with_parents_excluded, 5)
    assert buggy == [], "sanity check: seeding from the target's own id is the bug shape"

    fixed = research.upstream_chain(
        live, [q.xref for q in parents], known_with_parents_excluded, 5
    )
    assert fixed, "seeding from the parents themselves must reach the grandparents"


def test_propose_parents_includes_ancestors_at_depth_above_one() -> None:
    live = _three_generation_tree()
    target = live.people["F-TARGET"]
    entry = research.FrontierEntry(person=target, status="ready")
    entry.fs_parents = live.parents("F-TARGET")

    proposal = research.propose_parents(entry, live, known=set(), depth=3, docs={})
    assert "ancestors" in proposal, "depth=3 must propose ancestors above the parents"
    names = {p["given"] for level in proposal["ancestors"] for p in level}
    assert names == {"Grandfather", "Grandmother"}, names


def run() -> int:
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    if failures:
        print(f"\n{failures} FAILED")
    else:
        print("\nall checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())

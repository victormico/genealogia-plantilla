"""Regression test for `tools.research --depth`.

The bug it pins: `upstream_chain` used to start its walk from the *target*'s
own xref, whose parents were already in the `known` exclusion set (they are
the proposal's own `parents` block) -- so the very first hop always found
"nothing new" and stopped there, before ever reaching the grandparents. Any
`--depth` above 1 silently behaved like `--depth 1`: no `ancestors` section,
no matter how deep the live pedigree actually went.

`LiveTree` Person objects have `xref == fsftid` (both are the FamilySearch
id, see `tools/fs/fetch.py::_person_from_json`), which the fixtures below
mirror -- using different values for the two would hide the bug instead of
pinning it.

    python3 -m tools.tests.test_research
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

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


class _FakeApi:
    """Just enough Api to answer `citations`, with no session behind it.

    `corroborating_documents` is the only thing under test here, and what it
    needs from FamilySearch is one list per person. Standing up a real session
    to assert on a set intersection would test the network, not the rule.
    """

    class _NoSession:
        # No tree user id, so the contributor lookup sits this out and each
        # test below is about the citations and nothing else.
        tree_user_id = None

    def __init__(self, by_pid: dict[str, list[dict]]):
        self.by_pid = by_pid
        self.asked: list[str] = []
        self.fs = self._NoSession()

    def citations(self, pid: str) -> list[dict]:
        self.asked.append(pid)
        return self.by_pid.get(pid, [])


BAPTISM = {"url": "ark:/1786", "title": "bateig de 1786",
           "names": ["Antonio Baliente", "Juan Baliente"]}
BURIAL = {"url": "ark:/1807", "title": "defunció de 1807"}


def _entry_with_parents():
    live = _three_generation_tree()
    target = live.people["F-TARGET"]
    target.fsftid = "F-TARGET"
    entry = research.FrontierEntry(person=target, status="ready")
    entry.fs_parents = live.parents("F-TARGET")
    return live, entry


def test_a_shared_document_lifts_a_proposal_out_of_low() -> None:
    """The rule issue #70 is the reason for.

    Two parents entered by strangers with no birth dates is the `low` case --
    and it stays `low` however good the evidence is, because nothing was
    reading the evidence. A register entry attached to the child and to the
    father alike is FamilySearch saying one document covers them both.
    """
    live, entry = _entry_with_parents()
    api = _FakeApi({
        "F-TARGET": [BAPTISM],
        "F-FATHER": [BAPTISM, BURIAL],
        "F-MOTHER": [BURIAL],
    })

    without = research.propose_parents(entry, live, set(), 1, {}, api=None)
    assert without["confidence"] == "low", without["confidence"]

    with_docs = research.propose_parents(entry, live, set(), 1, {}, api=api)
    assert with_docs["confidence"] == "high", with_docs["confidence"]
    assert "anomena el target" in with_docs["why"], with_docs["why"]
    # Only the father shares the baptism, and the `why` has to say so rather
    # than imply the mother is corroborated too.
    assert "1 de 2 progenitors" in with_docs["why"], with_docs["why"]


def test_why_says_when_both_parents_are_corroborated() -> None:
    live, entry = _entry_with_parents()
    api = _FakeApi({
        "F-TARGET": [BAPTISM],
        "F-FATHER": [BAPTISM],
        "F-MOTHER": [BAPTISM],
    })
    proposal = research.propose_parents(entry, live, set(), 1, {}, api=api)
    assert "tots dos progenitors" in proposal["why"], proposal["why"]


def test_the_shared_document_is_flagged_on_the_parent_that_shares_it() -> None:
    live, entry = _entry_with_parents()
    api = _FakeApi({
        "F-TARGET": [BAPTISM],
        "F-FATHER": [BURIAL, BAPTISM],  # listed second by FamilySearch
        "F-MOTHER": [BURIAL],
    })
    proposal = research.propose_parents(entry, live, set(), 1, {}, api=api)
    father, mother = proposal["parents"]

    assert father["citations"][0]["url"] == "ark:/1786", "the shared one is hoisted to the top"
    assert father["citations"][0]["shared_with_target"] is True
    assert "shared_with_target" not in father["citations"][1], "the burial is his alone"
    assert not any(c.get("shared_with_target") for c in mother["citations"]), \
        "the mother shares nothing with the target and must not be flagged"


def test_unshared_documents_do_not_inflate_confidence() -> None:
    """Attached sources are common; *shared* ones are the signal.

    A parent with a dozen citations that have nothing to do with the child is
    exactly the well-worked stranger's entry the `low` rating is warning about.
    """
    live, entry = _entry_with_parents()
    api = _FakeApi({"F-TARGET": [], "F-FATHER": [BURIAL] * 12, "F-MOTHER": [BAPTISM]})
    proposal = research.propose_parents(entry, live, set(), 1, {}, api=api)
    assert proposal["confidence"] == "low", proposal["confidence"]


def test_citations_can_be_switched_off() -> None:
    live, entry = _entry_with_parents()
    api = _FakeApi({"F-TARGET": [BAPTISM], "F-FATHER": [BAPTISM]})
    proposal = research.propose_parents(entry, live, set(), 1, {}, api=api, citations=False)
    assert api.asked == [], "no requests may be spent when the flag is off"
    assert proposal["confidence"] == "low", proposal["confidence"]
    assert all("citations" not in q for q in proposal["parents"])


def test_a_long_source_list_is_trimmed() -> None:
    """Gil Gomez Valiente carries 55 attached sources. Printing them all would
    bury the one proposal line a reviewer has to read."""
    live, entry = _entry_with_parents()
    many = [{"url": f"ark:/{n}", "title": f"document {n}"} for n in range(40)]
    api = _FakeApi({"F-TARGET": [BAPTISM], "F-FATHER": many + [BAPTISM]})
    proposal = research.propose_parents(entry, live, set(), 1, {}, api=api)
    father = proposal["parents"][0]
    assert len(father["citations"]) == research.CITATIONS_SHOWN, len(father["citations"])
    assert father["citations"][0]["url"] == "ark:/1786", \
        "trimming must never drop the corroborating one"


def test_already_proposed_finds_only_pending_targets() -> None:
    """The bug this pins: a target proposed yesterday with `accept: null` (not
    yet reviewed) came back as a fresh-looking duplicate in today's file. A
    decided target -- true or false -- is not what this guards against, so
    only `null` entries should count."""
    with tempfile.TemporaryDirectory() as tmp:
        reports = Path(tmp)
        (reports / "candidates-2026-08-28.yaml").write_text(
            "- target: \"I00514\"\n  accept: null\n"
            "- target: \"I00540\"\n  accept: true\n"
            "- target: \"I00570\"\n  accept: false\n",
            encoding="utf-8",
        )
        pending = research.already_proposed(reports)
        assert "I00514" in pending, "an undecided target must be found"
        assert "I00540" not in pending, "an accepted target is decided, not pending"
        assert "I00570" not in pending, "a rejected target is decided, not pending"


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

"""Offline tests for `tools.fs.check`, the step that asks about the leftovers.

The regression this file pins is the distinction the whole step exists for:
**a person the pedigree never covered is not the same as a person FamilySearch
has no parents for.** The first is a question nobody asked, the second is an
answer. `pending()` must pick up the first and leave the second alone, or the
step either re-asks what it already knows (wasting somebody's request budget)
or quietly leaves people stranded in «Sense comprovar» for ever.

No network: the API is a stub that replays canned `ancestry` responses.

    python3 -m tools.tests.test_fs_check
"""

from __future__ import annotations

import sys

from tools.config import ROOT, example_tree
from tools.fs import check as check_mod
from tools.fs import fetch as fetch_mod
from tools.fs.check import check_person, dedupe_couples, pending, unanswered
from tools.fs.fetch import LiveTree
from tools.people import Person, Tree

CANONICAL = example_tree()

# The one leaf in exemple.ged carrying an _FSFTID -- the same anchor
# test_frontier.py uses, and the only person there who can be anything other
# than "unlinked".
LEAF_XREF, LEAF_FSFTID = "I00016", "KXQ2-8YT"

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


class StubApi:
    """Replays one canned ancestry response per PID, and counts the calls."""

    def __init__(self, answers: dict[str, dict | None]):
        self.answers = answers
        self.asked: list[str] = []

    def ancestry(self, pid: str, generations: int = 8) -> dict | None:
        self.asked.append(pid)
        return self.answers.get(pid)


def _ancestry(pid: str, with_parents: bool) -> dict:
    """A GEDCOM X ancestry response, Sosa-numbered the way FamilySearch does."""
    persons = [{"id": pid, "display": {"name": "Rita Vives", "ascendancyNumber": "1"}}]
    if with_parents:
        persons += [
            {"id": f"{pid}-F",
             "display": {"name": "Pare Vives", "ascendancyNumber": "2", "gender": "Male"}},
            {"id": f"{pid}-M",
             "display": {"name": "Mare Alcaraz", "ascendancyNumber": "3", "gender": "Female"}},
        ]
    return {"persons": persons}


def _person(pid: str) -> Person:
    return Person(
        xref=pid, name="Cobert /Test/", given="Cobert", surname="Test", sex=None,
        birth_date=None, birth_place=None, death_date=None, death_place=None,
        fsftid=pid, famc=None,
    )


def test_uncovered_person_is_pending(canon: Tree) -> None:
    print("\nqui el pedigrí no ha tocat mai queda pendent")
    live = LiveTree(root="ROOT-000")
    queue = pending(canon, live)
    check(
        any(p.xref == LEAF_XREF for p in queue),
        "la fulla enllaçada hi és, perquè el pedigrí no la cobreix",
        str([p.xref for p in queue]),
    )
    check(
        all(p.fsftid for p in queue),
        "cap persona sense _FSFTID no hi entra: primer cal trobar-la",
    )


def test_answered_person_is_not_re_asked(canon: Tree) -> None:
    print("\nqui el pedigrí sí que cobreix no es torna a preguntar")
    # In the pedigree, with no parent edges: that is FamilySearch's answer,
    # not a gap. Asking again would spend a request to be told the same thing.
    live = LiveTree(root="ROOT-000", people={LEAF_FSFTID: _person(LEAF_FSFTID)})
    queue = pending(canon, live)
    check(
        not any(p.xref == LEAF_XREF for p in queue),
        "una resposta negativa no és una pregunta pendent",
        str([p.xref for p in queue]),
    )


def test_skipped_leaf_is_pending(canon: Tree) -> None:
    print("\nles fulles que la cadena va deixar a la vuitena generació sí que ho són")
    live = LiveTree(
        root="ROOT-000",
        people={LEAF_FSFTID: _person(LEAF_FSFTID)},
        skipped_leaves=[LEAF_FSFTID],
    )
    check(unanswered(live) == {LEAF_FSFTID}, "surt com a no resposta")
    queue = pending(canon, live)
    check(
        any(p.xref == LEAF_XREF for p in queue),
        "és al pedigrí però ningú no li ha preguntat pels pares",
        str([p.xref for p in queue]),
    )


def test_check_person_moves_to_ready(canon: Tree) -> None:
    print("\ncomprovar una persona amb pares la deixa a punt d'importar")
    live = LiveTree(root="ROOT-000")
    person = canon.people[LEAF_XREF]
    api = StubApi({LEAF_FSFTID: _ancestry(LEAF_FSFTID, with_parents=True)})

    found = check_person(api, live, person)
    check(found == 2, "troba pare i mare", str(found))
    check(api.asked == [LEAF_FSFTID], "una sola consulta", str(api.asked))
    check(live.father_of.get(LEAF_FSFTID) == f"{LEAF_FSFTID}-F", "arestes de pare")
    check(live.mother_of.get(LEAF_FSFTID) == f"{LEAF_FSFTID}-M", "arestes de mare")
    check(not pending(canon, live), "ja no queda pendent")


def test_check_person_without_parents_still_answers(canon: Tree) -> None:
    print("\ncomprovar una persona sense pares també és una resposta")
    live = LiveTree(root="ROOT-000", skipped_leaves=[LEAF_FSFTID])
    person = canon.people[LEAF_XREF]
    api = StubApi({LEAF_FSFTID: _ancestry(LEAF_FSFTID, with_parents=False)})

    found = check_person(api, live, person)
    check(found == 0, "cap pare a FamilySearch", str(found))
    check(LEAF_FSFTID in live.people, "la persona queda al pedigrí")
    check(live.skipped_leaves == [], "deixa de comptar com a no resposta")
    check(
        not any(p.xref == LEAF_XREF for p in pending(canon, live)),
        "i per tant ja no es tornarà a preguntar",
    )


def test_unreachable_person_stays_pending(canon: Tree) -> None:
    print("\nun 403 o un 404 no es pot llegir com «no en té»")
    live = LiveTree(root="ROOT-000")
    person = canon.people[LEAF_XREF]
    api = StubApi({LEAF_FSFTID: None})  # Session.get returns None for 403/404

    found = check_person(api, live, person)
    check(found is None, "cap resposta, i no un zero", str(found))
    check(
        any(p.xref == LEAF_XREF for p in pending(canon, live)),
        "continua pendent en lloc de passar per encallada",
    )


def test_dedupe_couples() -> None:
    print("\nles parelles repetides no s'acumulen al fitxer")
    live = LiveTree(couples=[("A", "B"), ("A", "B"), ("C", "D"), ("A", "B")])
    dedupe_couples(live)
    check(live.couples == [("A", "B"), ("C", "D")], "una entrada per parella",
          str(live.couples))


def test_fetch_and_check_agree_on_the_pedigree_path() -> None:
    """The two halves must read and write the same file.

    They disagreed once, and silently: `fetch` derived its output path from
    `Path(__file__).parents[2]`, which is the repository only while `tools/` is
    a folder copied inside it. Installed as a package that is `site-packages`,
    so the fetch wrote the pedigree somewhere nothing else looks -- `check`
    reported no pedigree at all, and before this step existed `frontier` simply
    fell back to the committed snapshot and nobody noticed the live fetch was
    being thrown away. Both must come from `config.ROOT`.
    """
    print("\nfetch i check apunten al mateix pedigrí")
    check(
        fetch_mod.PEDIGREE == check_mod.PEDIGREE,
        "el mateix camí a totes dues bandes",
        f"{fetch_mod.PEDIGREE} vs {check_mod.PEDIGREE}",
    )
    check(
        fetch_mod.PEDIGREE == ROOT / "cache" / "pedigree.json",
        "i és dins del repositori, no del paquet instal·lat",
        str(fetch_mod.PEDIGREE),
    )
    check(
        "site-packages" not in str(fetch_mod.PEDIGREE),
        "mai sota site-packages",
        str(fetch_mod.PEDIGREE),
    )


def main() -> int:
    canon = Tree(CANONICAL)
    test_uncovered_person_is_pending(canon)
    test_answered_person_is_not_re_asked(canon)
    test_skipped_leaf_is_pending(canon)
    test_check_person_moves_to_ready(canon)
    test_check_person_without_parents_still_answers(canon)
    test_unreachable_person_stays_pending(canon)
    test_dedupe_couples()
    test_fetch_and_check_agree_on_the_pedigree_path()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

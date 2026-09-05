"""Acceptance tests for the frontier report and its FamilySearch snapshot.

The regression this file pins: without `cache/pedigree.json` (needs
credentials to refetch) `tools.frontier` used to call every leaf with an
`_FSFTID` "stuck" -- "FamilySearch also gives up here" -- which is a claim
nobody had checked. `test_no_source_is_never_stuck` is that pin: with neither
a live pedigree nor `reports/frontier-fs.json`, the status is `unknown`, not
`stuck`.

    python3 -m tools.tests.test_frontier
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from tools import lint
from tools.config import tree_path
from tools.estat import Estat
from tools.fs.fetch import LiveTree
from tools.frontier import (
    PEDIGREE,
    SNAPSHOT,
    FrontierEntry,
    build,
    documents_for,
    index_documents,
    rank,
    snapshot_load,
    snapshot_write,
    write_report,
)
from tools.people import Person, Tree
from tools.worklist import write_report as worklist_write_report

from tools.config import ROOT, example_tree
CANONICAL = example_tree()

# I00016 (Rita VIVES ALCARAZ) is exemple.ged's one leaf that carries an
# _FSFTID, which is what makes it possible to exercise ready/stuck/unknown at
# all -- everyone else without parents also lacks a FamilySearch link and is
# always "unlinked".
LEAF_XREF, LEAF_FSFTID = "I00016", "KXQ2-8YT"

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def _live_with_parents(canon: Tree) -> LiveTree:
    """A minimal fetched pedigree giving @I00016@'s FSFTID a father and mother."""
    father = Person(
        xref="F001", name="Pare /Fals/", given="Pare", surname="Fals", sex="M",
        birth_date="1 JAN 1850", birth_place="Ontinyent, València, Espanya",
        death_date=None, death_place=None, fsftid="F001", famc=None,
    )
    mother = Person(
        xref="M001", name="Mare /Falsa/", given="Mare", surname="Falsa", sex="F",
        birth_date="1 JAN 1852", birth_place="Ontinyent, València, Espanya",
        death_date=None, death_place=None, fsftid="M001", famc=None,
    )
    child = canon.people[LEAF_XREF]
    people = {LEAF_FSFTID: child, "F001": father, "M001": mother}
    return LiveTree(
        people=people,
        father_of={LEAF_FSFTID: "F001"},
        mother_of={LEAF_FSFTID: "M001"},
        couples=[("F001", "M001")],
        root=LEAF_FSFTID,
    )


def test_no_source_is_never_stuck(canon: Tree) -> None:
    print("\nsense pedigrí ni instantània, cap entrada no és «stuck»")
    entries = build(canon, None, None)
    stuck = [e for e in entries if e.status == "stuck"]
    check(not stuck, "cap entrada «stuck»", f"{len(stuck)} ho són")

    with_fsftid = [e for e in entries if e.person.fsftid]
    check(bool(with_fsftid), "hi ha almenys una entrada amb _FSFTID a l'arbre d'exemple")
    unknown = [e for e in with_fsftid if e.status == "unknown"]
    check(
        len(unknown) == len(with_fsftid),
        "totes les que tenen _FSFTID són «unknown»",
        f"{len(unknown)} de {len(with_fsftid)}",
    )

    unlinked = [e for e in entries if not e.person.fsftid]
    check(
        all(e.status == "unlinked" for e in unlinked),
        "les que no tenen _FSFTID continuen «unlinked»",
    )


def test_snapshot_round_trip(canon: Tree) -> None:
    print("\nla instantània fa la mateixa classificació que el pedigrí en viu")
    live = _live_with_parents(canon)
    live_entries = build(canon, live, None)
    live_entry = next(e for e in live_entries if e.person.xref == LEAF_XREF)
    check(live_entry.status == "ready", "amb pedigrí en viu, «ready»",
          live_entry.status)
    check(live_entry.upstream == 2, "dos avantpassats amunt (pare i mare)",
          str(live_entry.upstream))

    with tempfile.TemporaryDirectory() as tmp:
        snap_path = Path(tmp) / "frontier-fs.json"
        snapshot_write(live_entries, live.root, snap_path)
        snapshot = snapshot_load(snap_path)
        check(snapshot is not None, "la instantània es rellegeix")
        check(
            snapshot["persones"][LEAF_XREF]["fsftid"] == LEAF_FSFTID,
            "conté el fsftid de la persona",
        )

        snap_entries = build(canon, None, snapshot)
        snap_entry = next(e for e in snap_entries if e.person.xref == LEAF_XREF)
        check(snap_entry.status == "ready", "amb la instantània, també «ready»",
              snap_entry.status)
        check(snap_entry.upstream == live_entry.upstream,
              "el mateix nombre d'avantpassats amunt",
              f"{snap_entry.upstream} vs {live_entry.upstream}")
        got_parents = {p.xref for p in snap_entry.fs_parents}
        check(got_parents == {"F001", "M001"},
              "reconstrueix els dos progenitors", str(got_parents))


def test_mismatched_fsftid_is_ignored(canon: Tree) -> None:
    print("\nun fsftid que ja no coincideix es descarta")
    snapshot = {
        "data": "2020-01-01",
        "arrel": "X",
        "persones": {LEAF_XREF: {"fsftid": "NO-LONGER-THIS", "estat": "ready",
                                  "amunt": 5, "mes_antic": 1600, "pares": []}},
    }
    entries = build(canon, None, snapshot)
    entry = next(e for e in entries if e.person.xref == LEAF_XREF)
    check(entry.status == "unknown",
          "un fsftid desfasat a la instantània no s'accepta", entry.status)


def test_parented_person_leaves_the_report(canon: Tree) -> None:
    print("\nqui ja té pares desapareix encara que la instantània el recordi")
    non_leaf = next(p for p in canon.people.values() if p.famc)
    snapshot = {
        "data": "2020-01-01",
        "arrel": "X",
        "persones": {non_leaf.xref: {"fsftid": non_leaf.fsftid, "estat": "ready",
                                      "amunt": 3, "mes_antic": 1700, "pares": []}},
    }
    entries = build(canon, None, snapshot)
    xrefs = {e.person.xref for e in entries}
    check(non_leaf.xref not in xrefs,
          "una persona amb pares no surt al front de recerca encara que hi hagi "
          "una entrada vella a la instantània")


def test_write_report_is_deterministic(canon: Tree) -> None:
    print("\nl'informe és determinista i porta la capçalera")
    entries = build(canon, None, None)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frontier.md"
        write_report(entries, canon, None, None, path)
        first = path.read_text(encoding="utf-8")
        write_report(entries, canon, None, None, path)
        second = path.read_text(encoding="utf-8")
    check(first == second, "dues execucions donen el mateix text")
    check(first.startswith("# "), "comença amb un títol markdown")
    check("No s'edita a mà" in first, "diu que no s'edita a mà")
    check("Sense comprovar" in first, "la secció «Sense comprovar» hi és")


def _woman(given: str, surname: str, birth_date: str, birth_place: str) -> Person:
    return Person(
        xref="I09999", name=f"{given} /{surname}/", given=given, surname=surname,
        sex="F", birth_date=birth_date, birth_place=birth_place,
        death_date=None, death_place=None, fsftid=None, famc=None,
    )


# The document from the incident of 05-09-2026, path and all: a marriage of
# 1863 at Fontanars dels Alforins (València), whose filename happens to carry
# both «Maria» and «Garcia».
_MARRIAGE_1863 = (
    "Fonts/Arxiu Parroquial València/"
    "Josep_Biosca_Pascual_amb_Maria_Teresa_Garcia_Matrimoni_1863.md"
)


def test_a_name_match_across_a_century_is_not_a_document() -> None:
    print("\nel casador no pot confirmar amb un document de 128 anys després")
    docs = index_documents([ROOT / _MARRIAGE_1863])

    # The real proposal: María García, born 1735 at Jorquera (Albacete). One of
    # the commonest surnames in Spain is the only thing the two share, and
    # `frontier.md` printed it as «Confirmat per un document nostre».
    jorquera = _woman("MARÍA", "GARCÍA", "29 MAR 1735", "Jorquera, Albacete, Espanya")
    check(not documents_for(jorquera, docs, {}),
          "128 anys i dues províncies de distància no confirmen res")

    # Each guard on its own, so a change to one is visible: same province,
    # wrong century...
    early = _woman("MARIA", "GARCIA", "1735", "Fontanars dels Alforins, València")
    check(not documents_for(early, docs, {}), "la data sola ja ho descarta")

    # ...and, for a baptism, the same century in the wrong province. A baptism
    # is the one sacrament tied to where somebody was born.
    baptism = index_documents([
        ROOT / "Fonts/Arxiu Parroquial València/Maria_Garcia_Bateig_1840.md"
    ])
    elsewhere = _woman("MARÍA", "GARCÍA", "1840", "Jorquera, Albacete, Espanya")
    check(not documents_for(elsewhere, baptism, {}),
          "una parròquia de València no bateja qui va néixer a Albacete")

    # The marriage, though, stays: people move, and this tree has a branch from
    # Albacete precisely because somebody married into València. Dropping every
    # document from another province would lose every migrant's records.
    check(documents_for(elsewhere, docs, {}) == [_MARRIAGE_1863],
          "un matrimoni a l'altra província no és cap contradicció")

    # And the guess still works where it should: nothing above is a reason to
    # stop matching documents that could be about the person.
    hers = _woman("MARIA", "GARCIA", "1840", "Fontanars dels Alforins, València")
    check(documents_for(hers, docs, {}) == [_MARRIAGE_1863],
          "una coincidència plausible es manté")


def test_a_declaration_is_never_second_guessed() -> None:
    print("\nel que un document declara mana sobre qualsevol comprovació d'ací")
    docs = index_documents([ROOT / _MARRIAGE_1863])
    jorquera = _woman("MARÍA", "GARCÍA", "29 MAR 1735", "Jorquera, Albacete, Espanya")
    declared = {jorquera.xref: [_MARRIAGE_1863]}
    check(documents_for(jorquera, docs, declared) == [_MARRIAGE_1863],
          "si el document diu de qui parla, s'hi creu")


def test_a_guess_is_worth_less_than_a_declaration(canon: Tree) -> None:
    print("\nun document que només coincideix de nom puntua menys")
    person = next(iter(canon.people.values()))
    sure = FrontierEntry(person=person, status="stuck", documents=[_MARRIAGE_1863])
    guess = FrontierEntry(person=person, status="stuck", documents=[_MARRIAGE_1863],
                          guessed={_MARRIAGE_1863})
    check(rank(sure) > rank(guess),
          "una declaració ha de pesar més que una coincidència de noms",
          f"{rank(sure)} vs {rank(guess)}")


def test_check_informes(canon: Tree) -> None:
    print("\nel guardià a tools.lint --informes")
    estat = Estat(CANONICAL)

    # The same source `check_informes` will independently load: whatever is
    # really on disk right now (a fresh pedigree if there is one, else the
    # committed snapshot, else neither).
    live = None
    if PEDIGREE.exists():
        live = LiveTree.from_json(json.loads(PEDIGREE.read_text(encoding="utf-8")))
    snapshot = None if live else snapshot_load(SNAPSHOT)

    entries = build(canon, live, snapshot)
    with tempfile.TemporaryDirectory() as tmp:
        reports_dir = Path(tmp)
        write_report(entries, canon, live, snapshot, reports_dir / "frontier.md")
        worklist_write_report(entries, reports_dir / "worklist.md", live, snapshot)

        fresh = lint.Report()
        lint.check_informes(estat, fresh, reports_dir=reports_dir)
        check(not fresh.problems, "just generats, cap problema",
              "; ".join(fresh.problems[:2]))

        target = reports_dir / "frontier.md"
        original = target.read_text(encoding="utf-8")
        lines = original.split("\n")
        # Corrupt the first line carrying a count: the check must name the
        # file and the line.
        for i, line in enumerate(lines):
            if "Persones de l'arbre principal" in line:
                lines[i] = line.replace("**", "**9999", 1)
                break
        target.write_text("\n".join(lines), encoding="utf-8")

        broken = lint.Report()
        lint.check_informes(estat, broken, reports_dir=reports_dir)
        check(bool(broken.problems), "un informe alterat es detecta")
        check(
            any("reports/frontier.md:" in p for p in broken.problems),
            "i diu el fitxer i la línia",
            "; ".join(broken.problems[:2]),
        )


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    canon = Tree(CANONICAL)

    test_no_source_is_never_stuck(canon)
    test_snapshot_round_trip(canon)
    test_mismatched_fsftid_is_ignored(canon)
    test_parented_person_leaves_the_report(canon)
    test_write_report_is_deterministic(canon)
    test_a_name_match_across_a_century_is_not_a_document()
    test_a_declaration_is_never_second_guessed()
    test_a_guess_is_worth_less_than_a_declaration(canon)
    test_check_informes(canon)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

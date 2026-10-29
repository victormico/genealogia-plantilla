"""Offline tests for `tools.fs.fetch`, the chained walk up the pedigree.

The regression this file pins: **a plain fetch follows everyone at the eighth
generation.** Until 29-10-2026 it followed only the first 40 and listed the rest
in `skipped_leaves` with one printed line nobody read. Once the tree had more
than 40 people at generation 8 a fetch came back with 695 people instead of
1,631, and the reports called that pedigree «fresc».

No network: the API is a stub that serves a made-up ancestry.

    python3 -m tools.tests.test_fs_fetch
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools.frontier import (
    pedigree_provenance,
    snapshot_gaps,
    snapshot_load,
    snapshot_write,
)
from tools.fs.check import unanswered
from tools.fs.fetch import LiveTree, fetch_pedigree

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def _raw(pid: str, number: int) -> dict:
    return {"id": pid, "display": {"name": f"Persona {pid}", "ascendancyNumber": str(number)}}


def _full(pid: str, generations: int = 8, slot=lambda root, n: f"{root}.{n}") -> dict:
    """An ancestry with every Sosa slot filled up to `generations`."""
    persons = [_raw(pid, 1)]
    for number in range(2, 2 ** generations):
        persons.append(_raw(slot(pid, number), number))
    return {"persons": persons}


class StubApi:
    """Serves canned ancestries; anyone else comes back with just their parents."""

    def __init__(self, answers: dict[str, dict]):
        self.answers = answers
        self.asked: list[str] = []

    def ancestry(self, pid: str, generations: int = 8) -> dict | None:
        self.asked.append(pid)
        return self.answers.get(pid) or _full(pid, generations=2)


def test_everyone_at_generation_8_is_followed() -> None:
    print("\nper defecte es re-arrela tota la vuitena generació")
    api = StubApi({"ROOT": _full("ROOT")})
    tree = fetch_pedigree(api, "ROOT", verbose=False)
    eighth = [f"ROOT.{n}" for n in range(128, 256)]
    check(len(eighth) > 40, "més de 40 persones a la generació 8", str(len(eighth)))
    check(set(api.asked[1:]) == set(eighth), "totes es re-arrelen",
          f"{len(api.asked) - 1} de {len(eighth)}")
    check(tree.calls == 1 + len(eighth), "una crida per persona i prou", str(tree.calls))
    check(tree.skipped_leaves == [], "cap fulla saltada", str(len(tree.skipped_leaves)))
    check(all(tree.parents(pid) for pid in eighth), "totes tenen els pares")
    check("skipped=0 " in repr(tree), "el resum ho diu", repr(tree))


def test_depth_stops_at_generation_15() -> None:
    print("\nper defecte s'arriba a la generació 15, i qui hi ha dalt es registra")
    api = StubApi({"ROOT": _full("ROOT"), "ROOT.128": _full("ROOT.128")})
    tree = fetch_pedigree(api, "ROOT", verbose=False)
    # The re-rooted call starts at generation 8, so its own eighth is the 15th.
    fifteenth = "ROOT.128.128"
    check(tree.generation(fifteenth) == 15, "és a la generació 15",
          str(tree.generation(fifteenth)))
    check(fifteenth not in api.asked, "no s'hi torna a re-arrelar")
    check(set(tree.beyond_depth) == {f"ROOT.128.{n}" for n in range(128, 256)},
          "la vuitena de la crida encadenada va a beyond_depth",
          str(len(tree.beyond_depth)))
    check(tree.skipped_leaves == [], "però el pedigrí no és incomplet")
    check(unanswered(tree) >= set(tree.beyond_depth),
          "tools.fs.check les compta com a no preguntades")
    line = pedigree_provenance(tree)
    check("Incomplet" not in line and "128" in line and "--depth" in line,
          "la capçalera ho diu sense dir-ne incomplet", line)
    round_trip = LiveTree.from_json(tree.to_json())
    check(round_trip.beyond_depth == tree.beyond_depth, "es conserva al fitxer")


def test_depth_2_follows_generation_15() -> None:
    print("\namb --depth 2 la vuitena generació d'una crida encadenada també es segueix")
    api = StubApi({"ROOT": _full("ROOT"), "ROOT.128": _full("ROOT.128")})
    tree = fetch_pedigree(api, "ROOT", verbose=False, depth=2)
    fifteenth = "ROOT.128.128"
    check(fifteenth in api.asked, "s'hi torna a re-arrelar")
    check(len(tree.parents(fifteenth)) == 2, "i se'n tenen els pares, a la 16")
    check(tree.beyond_depth == [], "no queda ningú per sobre", str(tree.beyond_depth))


def test_implex_is_asked_once() -> None:
    print("\nqui surt dues vegades a la vuitena generació es pregunta una vegada")
    # Sosa 128 and 129 are the same person.
    same = lambda root, n: "IMPLEX" if n in (128, 129) else f"{root}.{n}"
    api = StubApi({"ROOT": _full("ROOT", slot=same)})
    fetch_pedigree(api, "ROOT", verbose=False)
    check(api.asked.count("IMPLEX") == 1, "una sola crida", str(api.asked.count("IMPLEX")))


def test_cap_is_visible() -> None:
    print("\nun tall amb --max-chained es veu al resum i a l'informe")
    api = StubApi({"ROOT": _full("ROOT")})
    tree = fetch_pedigree(api, "ROOT", max_chained=40, verbose=False)
    check(tree.calls == 41, "40 crides encadenades", str(tree.calls))
    check(len(tree.skipped_leaves) == 128 - 40, "la resta queda a skipped_leaves",
          str(len(tree.skipped_leaves)))
    check(not set(tree.skipped_leaves) & set(api.asked), "cap saltada no s'ha preguntat")
    check("skipped=88 " in repr(tree), "el resum diu quantes", repr(tree))
    line = pedigree_provenance(tree)
    check("Incomplet" in line and "88" in line, "la capçalera avisa", line)
    check("Incomplet" not in pedigree_provenance(LiveTree(root="ROOT")),
          "i un pedigrí sencer no porta l'avís")
    round_trip = LiveTree.from_json(tree.to_json())
    check(round_trip.skipped_leaves == tree.skipped_leaves, "es conserva al fitxer")


def test_gaps_reach_the_snapshot() -> None:
    print("\nl'avís arriba als informes comesos, que surten de la instantània")
    tree = LiveTree(root="ROOT", skipped_leaves=["A", "B"], beyond_depth=["C"])
    with tempfile.TemporaryDirectory() as tmp:
        path = snapshot_write([], tree.root, Path(tmp) / "frontier-fs.json", tree)
        snapshot = snapshot_load(path)
    check(snapshot.get("saltades") == 2 and snapshot.get("per_sobre") == 1,
          "la instantània porta els recomptes", str(snapshot))
    gaps = snapshot_gaps(snapshot)
    check("Incomplet:** 2" in gaps and pedigree_provenance(tree).endswith(gaps),
          "i en surt el mateix avís que del pedigrí", gaps)
    with tempfile.TemporaryDirectory() as tmp:
        path = snapshot_write([], "ROOT", Path(tmp) / "frontier-fs.json", LiveTree(root="ROOT"))
        clean = snapshot_load(path)
    check("saltades" not in clean and snapshot_gaps(clean) == "",
          "un pedigrí sencer no hi deixa res", str(clean))


def main() -> int:
    test_everyone_at_generation_8_is_followed()
    test_depth_stops_at_generation_15()
    test_depth_2_follows_generation_15()
    test_implex_is_asked_once()
    test_cap_is_visible()
    test_gaps_reach_the_snapshot()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

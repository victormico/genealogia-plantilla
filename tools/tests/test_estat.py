"""Acceptance tests for the computed numbers and the checks over them.

Run against `exemple.ged`, so the numbers pinned here are facts about the
example tree, not about anyone's real family -- they exist so that
`tools.estat` and `tools.lint --xifres` cannot silently start lying without a
test noticing.

    python3 -m tools.tests.test_estat
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools import report
from tools.estat import Estat, render
from tools.lint import Report, check_cr_id, check_rutes, check_xifres
from tools.people import Tree

from tools import config
from tools.config import ROOT, example_tree
CANONICAL = example_tree()

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_generation_table(estat: Estat) -> None:
    print("\nla taula de generacions")
    check(estat.root == "I00001", "l'arrel per defecte és qui té el Sosa 1",
          str(estat.root))

    expected = {1: 1, 2: 2, 3: 4, 4: 4, 5: 4, 6: 2}
    for gen, want in expected.items():
        got, _ = estat.generation(gen)
        check(got == want, f"G{gen} = {want}", f"és {got}")
    check(7 not in estat.slots, "no hi ha G7: la G6 no té pares coneguts")

    check(
        estat.total_slots == sum(expected.values()),
        "les files sumen el total",
        f"{estat.total_slots} vs {sum(expected.values())}",
    )
    check(estat.implex == estat.total_slots - estat.distinct_ancestors,
          "l'implex és caselles menys persones")
    check(estat.implex == 0, "l'arbre d'exemple no té implex", f"és {estat.implex}")
    check(not estat.foster_slots, "cap `PEDI foster` a l'arbre d'exemple",
          str(estat.foster_slots))


def test_foster_shrinks_a_generation() -> None:
    """A synthetic tree, not exemple.ged: pins the genealogical judgement itself.

    `Tree.ancestors(birth_only=True)` must stop at a `2 PEDI foster` FAMC rather
    than reporting a biological line no document supports. This is exercised on
    a tiny in-memory GEDCOM so the example tree does not need a foster case of
    its own to prove the mechanism works.
    """
    print("\nel `2 PEDI foster` talla el recorregut")
    text = """\
0 HEAD
1 GEDC
2 VERS 5.5.1
0 @I01@ INDI
1 NAME Net /Exemple/
1 FAMC @F01@
0 @I02@ INDI
1 NAME Pare /Criança/
1 FAMS @F01@
0 @I03@ INDI
1 NAME Mare /Criança/
1 FAMS @F01@
0 @F01@ FAM
1 HUSB @I02@
1 WIFE @I03@
1 CHIL @I01@
0 TRLR
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "foster.ged"
        path.write_text(text, encoding="utf-8")
        tree = Tree(path)

        birth = tree.ancestors("I01")
        check(2 in birth, "sense PEDI, G2 hi és", str(birth))
        check(len(birth.get(2, [])) == 2, "amb els dos progenitors")

        # Now mark the FAMC as foster and rebuild the file text so the
        # PEDI line sits under the FAMC it belongs to.
        fostered = text.replace(
            "1 FAMC @F01@\n", "1 FAMC @F01@\n2 PEDI foster\n", 1
        )
        path.write_text(fostered, encoding="utf-8")
        tree2 = Tree(path)
        check(not tree2.people["I01"].famc_is_birth, "famc_is_birth és fals")

        walked = tree2.ancestors("I01")
        check(2 not in walked or not walked[2],
              "amb PEDI foster, el recorregut s'atura a G1", str(walked))

        walked_all = tree2.ancestors("I01", birth_only=False)
        check(len(walked_all.get(2, [])) == 2,
              "birth_only=False encara hi arriba", str(walked_all))

        # And the configurable rule: a tree that counts `foster` as ancestry
        # walks through the same link without walking through everything.
        counted = tree2.ancestors("I01", counted={"birth", "foster"})
        check(len(counted.get(2, [])) == 2,
              "amb `foster` comptat, la G2 hi torna a ser", str(counted))
        check(tree2.people["I01"].famc_counts({"birth", "foster"}),
              "famc_counts diu que sí amb la regla que el compta")
        check(not tree2.people["I01"].famc_counts({"birth"}),
              "i que no amb la regla per defecte")
        adopted = tree2.ancestors("I01", counted={"birth", "adopted"})
        check(2 not in adopted or not adopted[2],
              "comptar `adopted` no arrossega el `foster`", str(adopted))


def test_counted_filiations() -> None:
    """The config knob itself: which `2 PEDI` values count as ancestry."""
    print("\nquines filiacions compten")
    check(config.counted_filiations() == {"birth"},
          "la plantilla compta només la de sang",
          str(config.counted_filiations()))

    def read(value):
        config.load.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(value, encoding="utf-8")
            original = config.CONFIG_PATH
            config.CONFIG_PATH = path
            try:
                return config.counted_filiations()
            finally:
                config.CONFIG_PATH = original
                config.load.cache_clear()

    check(read("estat:\n  filiacions_que_compten: [birth, foster]\n")
          == {"birth", "foster"}, "una llista es llegeix tal qual")
    check(read("estat:\n  filiacions_que_compten: FOSTER\n") == {"foster"},
          "un sol valor, i les majúscules no importen")
    check(read("estat:\n  arrel: I01\n") == {"birth"},
          "sense la clau, la de sang i prou")
    check(read("estat:\n  filiacions_que_compten: []\n") == {"birth"},
          "una llista buida no deixa l'arbre sense cap generació")
    try:
        read("estat:\n  filiacions_que_compten: [criança]\n")
    except config.ConfigError as exc:
        check("filiacions_que_compten" in str(exc),
              "un valor que no és del GEDCOM s'atura i diu què acceptaria",
              str(exc))
    else:
        check(False, "un valor que no és del GEDCOM s'atura")


def test_counts(estat: Estat) -> None:
    print("\nels recomptes de portada")
    check(estat.people == 18, "18 persones", f"són {estat.people}")
    check(estat.families == 8, "8 famílies", f"són {estat.families}")
    check(estat.with_fsftid == 7, "7 amb _FSFTID", f"són {estat.with_fsftid}")
    check(estat.without_parents == 9, "9 sense pares",
          f"són {estat.without_parents}")
    check(estat.period == (1845, 2019), "període 1845-2019", str(estat.period))

    routes, lines, broken = estat.gedcom_paths()
    check(not broken, "cap ruta de Fonts/ trencada", str(broken[:3]))
    check(routes >= 1, "almenys una ruta de Fonts/ citada", str(routes))


def test_checks_are_read_only(estat: Estat) -> None:
    print("\nles comprovacions no toquen res")
    watched = [ROOT / "README.md", CANONICAL]
    before = {p: p.read_bytes() for p in watched if p.exists()}

    collected = Report()
    check_xifres(estat, collected)
    check_rutes(estat, collected)
    check_cr_id(collected)

    for path, original in before.items():
        check(path.read_bytes() == original, f"{path.name} no s'ha tocat")


def test_writer_guard() -> None:
    """The guard against exactly the corruption a redirected stdout can cause."""
    print("\nel guardià de l'escriptor")
    stdout_pasted = (
        "9 dead-ends: 0 ready, 0 stuck, 1 unknown, 8 unlinked\n"
        "0 ancestors importable from FamilySearch\n"
        "wrote reports/frontier.md\n"
        "r |\n"
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "frontier.md"

        try:
            report.write(path, stdout_pasted)
            check(False, "refusa text que no comença per «# »")
        except report.Refused:
            check(True, "refusa text que no comença per «# »")

        report.write(path, "# Front de recerca\n\ntext\n")
        check(path.read_text(encoding="utf-8").startswith("# "),
              "accepta un informe de debò")

        path.write_text(stdout_pasted, encoding="utf-8")
        try:
            report.write(path, "# Front de recerca\n\nnou\n")
            check(False, "refusa sobreescriure un fitxer ja corromput")
        except report.Refused:
            check(True, "refusa sobreescriure un fitxer ja corromput")

        report.write(path, "# Front de recerca\n\nnou\n", force=True)
        check(path.read_text(encoding="utf-8").startswith("# Front"),
              "amb force el repara")

    # And the committed reports must not be in that state right now.
    for name in ("frontier.md", "worklist.md", "estat.md", "duplicacio.md"):
        path = ROOT / "reports" / name
        if path.exists():
            check(path.read_text(encoding="utf-8").startswith("# "),
                  f"reports/{name} comença per «# »")


def test_break_it_on_purpose(estat: Estat) -> None:
    """Una comprovació que sempre passa és sospitosa.

    El README de la plantilla no porta cap taula d'estat -- res a trencar-hi
    de partida --, així que aquest test n'hi afig una amb una xifra
    equivocada, la comprova i la treu. El punt és el mateix: que `--xifres`
    sap dir quin fitxer i quina línia, no només que hi ha un problema.
    """
    print("\ntrencant-ho a posta")

    # In a temporary directory, never in the repository this happens to be
    # installed into: a test that rewrites somebody's README and restores it
    # afterwards is one interrupted run away from losing their file.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        readme = root / "README.md"
        original = "# Prova\n\nUna taula d'estat:\n\n|  |  |\n| --- | --- |\n"
        readme.write_text(original, encoding="utf-8")

        baseline = Report()
        check_xifres(estat, baseline, root=root)
        check(not baseline.problems, "de partida no hi ha cap xifra desfasada",
              "; ".join(baseline.problems[:3]))

        wrong_row = f"| Persones a l'arbre | {estat.people - 1} |"
        readme.write_text(original + f"\n{wrong_row}\n", encoding="utf-8")
        collected = Report()
        check_xifres(estat, collected, root=root)
        named = [p for p in collected.problems if "Persones a l'arbre" in p]
        check(bool(named), "--xifres falla i anomena la fila")
        check(any("README.md:" in p for p in named),
              "i diu el fitxer i la línia", str(named[:1]))

        # The other half: a generation row, whose total is not a number anybody
        # should be typing either. G6 has 2**5 = 32 slots whatever the tree.
        filled, _ = estat.generation(6)
        readme.write_text(
            original + f"\n| Sisena generació | **{filled + 1} de 32** |\n",
            encoding="utf-8",
        )
        collected = Report()
        check_xifres(estat, collected, root=root)
        named = [p for p in collected.problems if "Sisena generació" in p]
        check(bool(named), "--xifres comprova també les files de generació",
              "; ".join(collected.problems[:3]))
        check(any(f"{filled} de 32" in p for p in named),
              "i diu quantes caselles són de veres", str(named[:1]))



def test_render_is_deterministic(estat: Estat) -> None:
    print("\nl'informe és determinista")
    first = render(estat)
    second = render(Estat(CANONICAL, root=estat.root))
    check(first == second, "dues execucions donen el mateix text")
    check(first.startswith("# "), "comença amb un títol markdown")
    check("No s'edita a mà" in first, "diu que no s'edita a mà")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "estat.md"
        out.write_text(first, encoding="utf-8")
        check(out.read_text(encoding="utf-8") == first, "es pot escriure i rellegir")



def _example_root(path) -> str | None:
    """Whoever carries `_SOSADABOVILLE 1` in the example tree."""
    for person in Tree(path).people.values():
        if person.sosa and person.sosa.split()[0] == "1":
            return person.xref
    return None


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    # Explicitly the example tree AND its own root: `estat: arrel:` in the
    # config of whatever repository this is installed into would otherwise
    # point at a person the example tree has never heard of, and every pinned
    # number below would be measuring the wrong tree.
    estat = Estat(CANONICAL, root=_example_root(CANONICAL))
    test_generation_table(estat)
    test_foster_shrinks_a_generation()
    test_counted_filiations()
    test_counts(estat)
    test_checks_are_read_only(estat)
    test_writer_guard()
    test_break_it_on_purpose(estat)
    test_render_is_deterministic(estat)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

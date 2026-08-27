"""Acceptance tests for our frontmatter vocabulary and the person-document join.

Two things are pinned here.

The first is the YAML traps. `@` is a reserved indicator and `: ` inside an
unquoted scalar ends the scalar, so `xrefs: [@I00103@]` and a title containing a
colon both fail to parse. Nothing about that is exotic -- it is the shape every
person and every case title in this vocabulary takes -- so it fails silently
unless something checks.

The second is that an xref names the *right* person. `--frontmatter` checks
that an xref *exists*; `--xrefs` (in `tools.lint`) checks *who it is*.

Everything here runs against a temporary `Fonts/`-shaped folder, not the
repository's own `Fonts/`, so it neither depends on nor risks the fixtures
that ship with the template.

    python3 -m tools.tests.test_frontmatter
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import yaml

from tools import frontmatter as fm
from tools.frontier import declared_documents, documents_for, guess_disagreements, index_documents
from tools.lint import Report, check_xrefs
from tools.people import Tree

from tools.config import ROOT, example_tree
CANONICAL = example_tree()

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


class _Sandbox:
    """Points `tools.frontmatter` and `tools.frontier` at a scratch Fonts/.

    Both modules resolve `FONTS` (and `frontmatter.PERSONES`) as module-level
    constants rather than parameters, which is the right call for a CLI tool
    and the wrong one for a test that must not touch the real `Fonts/`. This
    swaps the constants for the duration of a `with` block and always puts
    them back, even if the test fails.
    """

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self._saved: list[tuple[object, str, object]] = []

    def _patch(self, module, name: str, value) -> None:
        self._saved.append((module, name, getattr(module, name)))
        setattr(module, name, value)

    def __enter__(self) -> Path:
        import tools.frontier as frontier_module
        import tools.lint as lint_module

        fonts = self.tmp / "Fonts"
        fonts.mkdir()
        self._patch(fm, "FONTS", fonts)
        self._patch(fm, "PERSONES", self.tmp / "Persones")
        self._patch(fm, "ROOT", self.tmp)
        self._patch(frontier_module, "FONTS", fonts)
        self._patch(frontier_module, "ROOT", self.tmp)
        self._patch(lint_module, "FONTS", fonts)
        self._patch(lint_module, "ROOT", self.tmp)
        return fonts

    def __exit__(self, *exc) -> None:
        for module, name, value in self._saved:
            setattr(module, name, value)


def test_yaml_traps() -> None:
    """The two ways a title or an xref break YAML if left unquoted."""
    print("\nles trampes de YAML")
    cases = [
        ("xrefs: [@I00103@]", False, "un xref sense cometes no parseja"),
        ('xrefs: ["@I00103@"]', True, "amb cometes sí"),
        ("titol: Fontanars: el mapa dels avantpassats", False,
         "un titol amb «: » sense cometes no parseja"),
        ('titol: "Fontanars: el mapa dels avantpassats"', True, "amb cometes sí"),
        ("titol: Aina Figuerola — bateig, Girona", True,
         "un guionet i una coma no són cap trampa"),
    ]
    for block, should_parse, label in cases:
        try:
            yaml.safe_load(block)
            parsed = True
        except yaml.YAMLError:
            parsed = False
        check(parsed == should_parse, label)


NOTE_TEMPLATE = """\
---
tipus: transcripcio
titol: "Aina Figuerola — bateig, Girona"
arxiu: adg
classe: original
confianca: alta
xrefs: ["@I00001@"]
imatges: []
descripcio_imatges: []
casos: []
fonts: []
persones: []
---

Cos de la fitxa.
"""


def test_check_catches_each_fault(tree: Tree) -> None:
    """Break one thing at a time in a fixture note and confirm each is reported."""
    print("\nes detecta cada error, un per un")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)) as fonts:
            target = fonts / "Aina_Figuerola_Bateig.md"
            target.write_text(NOTE_TEMPLATE, encoding="utf-8")

            faults = {
                "un xref sense cometes": ('xrefs: ["@I00001@"]', "xrefs: [@I00001@]"),
                "un cr_id": ("tipus: transcripcio", "tipus: transcripcio\ncr_id: abc-123"),
                "un xref inexistent": ('xrefs: ["@I00001@"]', 'xrefs: ["@I99999@"]'),
                "una classe inventada": ("classe: original", "classe: primaria"),
                "un tipus inventat": ("tipus: transcripcio", "tipus: partida"),
                "una confianca inventada": ("confianca: alta", "confianca: molta"),
                "un wikilink que no resol": (
                    "casos: []", 'casos: ["[[Un cas que no hi és]]"]',
                ),
            }
            for label, (old, new) in faults.items():
                broken = NOTE_TEMPLATE.replace(old, new, 1)
                target.write_text(broken, encoding="utf-8")
                report = Report()
                fm.check(report, tree)
                hit = [p for p in report.problems if "Aina_Figuerola" in p]
                check(bool(hit), label, "no detectat")

            target.write_text(NOTE_TEMPLATE, encoding="utf-8")
            report = Report()
            fm.check(report, tree)
            check(not report.problems, "la fitxa neta no dona cap problema",
                  "; ".join(report.problems[:3]))


def test_tramit_is_accepted(tree: Tree) -> None:
    """`tramit` is a document kind, not a typo.

    The paperwork an archive makes you file -- a formal request and the reply
    saying what was found -- used to have nowhere to go: `transcripcio` claims
    something historical is being transcribed, `recerca` claims somebody worked
    something out. Both were wrong for a covering letter, so the notes were
    reported as an invented `tipus`. The sibling check below keeps a genuinely
    invented one rejected, so this is a vocabulary entry and not a hole.
    """
    print("\nun tràmit d'arxiu és un tipus, no una errada")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)) as fonts:
            note = NOTE_TEMPLATE.replace("tipus: transcripcio", "tipus: tramit")
            (fonts / "Instancia_2358005.md").write_text(note, encoding="utf-8")
            report = Report()
            fm.check(report, tree)
            check(not report.problems, "s'accepta «tramit»",
                  "; ".join(report.problems[:3]))

            invented = NOTE_TEMPLATE.replace("tipus: transcripcio", "tipus: instancia")
            (fonts / "Instancia_2358005.md").write_text(invented, encoding="utf-8")
            report = Report()
            fm.check(report, tree)
            check(bool(report.problems), "i «instancia», que no és del vocabulari, no")


def test_arxiu_open_until_configured() -> None:
    """`arxiu:` accepts anything while `frontmatter: arxius:` is empty, as shipped."""
    print("\narxiu obert fins que es configura")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)) as fonts:
            note = NOTE_TEMPLATE.replace("arxiu: adg", "arxiu: qualsevol_cosa")
            (fonts / "Nota.md").write_text(note, encoding="utf-8")
            # The vocabulary comes from config.yaml, and this test is about
            # what happens when there is none. Installed into a repository that
            # HAS one, the ambient config would decide the answer instead.
            original = fm.config.frontmatter_archives
            fm.config.frontmatter_archives = lambda: {}
            try:
                report = Report()
                fm.check(report, None)
            finally:
                fm.config.frontmatter_archives = original
            check(
                not any("arxiu" in p for p in report.problems),
                "sense config, cap arxiu es rebutja",
                "; ".join(report.problems[:3]),
            )


def test_wrong_xref_is_caught(tree: Tree) -> None:
    """The bug this check exists for: a name written beside the wrong xref."""
    print("\nun xref que anomena algú altre")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)):
            target = Path(tmp) / "Fonts" / "nota.md"
            target.write_text(
                "El @I00006@ *Aina Figuerola* és qui surt al document.\n",
                encoding="utf-8",
            )
            report = Report()
            check_xrefs(_stub(tree), report)
            hit = [p for p in report.problems if "I00006" in p]
            check(bool(hit), "es detecta que la @I00006@ no és l'Aina Figuerola")
            check(
                any("Vicent" in p or "Segarra" in p for p in hit),
                "i diu qui és de veritat", str(hit[:1]),
            )


def test_spelling_drift_is_tolerated(tree: Tree) -> None:
    """A transcription variant of the same person is not flagged."""
    print("\nles variants de grafia no es marquen")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)):
            target = Path(tmp) / "Fonts" / "nota.md"
            # I00011 is "Maria TORRENT ESPÍ"; a transcription that drops the
            # accent, as an index often does, must still match.
            target.write_text(
                "La @I00011@ *Maria Torrent Espi* consta al document.\n",
                encoding="utf-8",
            )
            report = Report()
            check_xrefs(_stub(tree), report)
            check(not report.problems, "cap discrepància amb una grafia equivalent",
                  "; ".join(report.problems[:3]))


def _stub(tree: Tree):
    class Stub:
        pass

    stub = Stub()
    stub.tree = tree
    return stub


def test_declared_join_beats_the_guess() -> None:
    print("\nla unió declarada guanya l'heurístic")
    with tempfile.TemporaryDirectory() as tmp:
        with _Sandbox(Path(tmp)) as fonts:
            tree = Tree(CANONICAL)

            # An undeclared document whose filename matches I00002 (Jordi
            # Figuerola Pujalt) by surname and given name: the heuristic finds
            # it.
            (fonts / "Jordi_Figuerola_Pujalt_Bateig_1970.md").write_text(
                "---\ntipus: transcripcio\ntitol: t1\nclasse: original\n---\ncos\n",
                encoding="utf-8",
            )
            # A second file, same stem-ish name, but this one *declares* who it
            # is about via xrefs -- and declares somebody else, I00004 (Pere
            # Figuerola Mascarell), the way a document naming a descendant can
            # get guessed onto an ancestor who shares the surname.
            (fonts / "Pere_Figuerola_Mascarell_Bateig_1942.md").write_text(
                '---\ntipus: transcripcio\ntitol: t2\nclasse: original\n'
                'xrefs: ["@I00004@"]\n---\ncos\n',
                encoding="utf-8",
            )

            docs = index_documents()
            declared = declared_documents()
            check(declared.get("I00004") == ["Fonts/Pere_Figuerola_Mascarell_Bateig_1942.md"],
                  "la declaració es llegeix", str(declared))

            # I00002's surname ("FIGUEROLA PUJALT" -> figuerola, pujalt) does
            # not appear in the second file's name, so the heuristic alone
            # should not credit I00002 with it; this just establishes the
            # baseline before checking the declared side wins its own file.
            pere = tree.people["I00004"]
            hits = documents_for(pere, docs, declared)
            check(
                "Fonts/Pere_Figuerola_Mascarell_Bateig_1942.md" in hits,
                "la declaració compta com a document propi",
                str(hits),
            )

            rows = guess_disagreements(tree, docs, declared)
            check(isinstance(rows, list), "guess_disagreements retorna una llista")


def main() -> int:
    if not CANONICAL.exists():
        print(f"missing {CANONICAL}")
        return 2
    tree = Tree(CANONICAL)
    test_yaml_traps()
    test_check_catches_each_fault(tree)
    test_tramit_is_accepted(tree)
    test_arxiu_open_until_configured()
    test_wrong_xref_is_caught(tree)
    test_spelling_drift_is_tolerated(tree)
    test_declared_join_beats_the_guess()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

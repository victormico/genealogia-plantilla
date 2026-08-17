"""Acceptance tests for tools.archive and the reports/descartades/ split it feeds.

`tools.archive` is the only place that moves `accept: false` entries out of a
review file, and `tools.research.previously_rejected` is the only place that
reads them back afterwards -- from both `reports/` and `reports/descartades/`,
because a rejection that has already been archived must still keep a proposal
from coming back next week. The two are tested together here because neither
one means anything on its own.

    python3 -m tools.tests.test_archive
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from tools import archive, research

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


FIXTURE = """\
# candidats de prova. Res no toca el GEDCOM fins que ho acceptis aquí.
#
# accept: true   -> s'incorpora
# accept: false  -> es descarta
# accept: null   -> pendent (no es fa res)

- target: "I00001"
  # ja decidit que sí
  why: "prova"
  accept: true

- target: "I00002"
  # ja decidit que no
  why: "prova"
  accept: false

- target: "I00003"
  # encara sense decidir
  why: "prova"
  accept: null
"""


def test_split_three_ways() -> None:
    """`accept: true` -> aplicades/, `accept: false` -> descartades/, null stays."""
    print("\ntools.archive: divideix en tres")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        reports = root / "reports"
        reports.mkdir()
        archived, discarded = reports / "aplicades", reports / "descartades"
        orig_archive, orig_discard = archive.ARCHIVE, archive.DISCARDED
        archive.ARCHIVE, archive.DISCARDED = archived, discarded
        try:
            candidates = reports / "candidates-test.yaml"
            candidates.write_text(FIXTURE, encoding="utf-8")

            plan = archive.plan_file(candidates, "17-08-2026")
            check(plan is not None, "hi ha alguna cosa a moure")
            assert plan is not None
            check(plan["done"] == 1, "una entrada aplicada", str(plan["done"]))
            check(plan["discarded_n"] == 1, "una entrada descartada", str(plan["discarded_n"]))
            check(plan["keep"] == 1, "una entrada pendent es queda", str(plan["keep"]))
            check("I00001" in plan["archived"], "l'entrada aplicada és al text arxivat")
            check("I00002" in plan["discarded"], "l'entrada descartada és al text descartat")
            check("I00001" not in plan["discarded"], "l'aplicada no es filtra al descartat")
            check("I00002" not in plan["archived"], "la descartada no es filtra a l'arxiu")
            check("I00003" in plan["remaining"], "la pendent es queda al fitxer original")
            check("I00001" not in plan["remaining"], "l'aplicada surt del fitxer original")
            check("I00002" not in plan["remaining"], "la descartada surt del fitxer original")

            # --write really moves the files, and only creates the folder it needs.
            sys.argv = ["tools.archive", "--reports", str(reports), "--write"]
            rc = archive.main()
            check(rc == 0, "main() torna 0")
            check((archived / "candidates-test.yaml").exists(), "aplicades/ escrit")
            check((discarded / "candidates-test.yaml").exists(), "descartades/ escrit")
            check(candidates.exists(), "el fitxer original es queda (encara hi ha pendents)")
            check(
                "I00003" in candidates.read_text(encoding="utf-8"),
                "el fitxer original només conserva la pendent",
            )

            # A second run with nothing new to move is a no-op, not an error.
            sys.argv = ["tools.archive", "--reports", str(reports), "--write"]
            rc2 = archive.main()
            check(rc2 == 0, "una segona passada sense res nou torna 0")
        finally:
            archive.ARCHIVE, archive.DISCARDED = orig_archive, orig_discard


def test_research_reads_both_folders() -> None:
    """`previously_rejected` must not stop reading a rejection once it's archived."""
    print("\ntools.research: llegeix reports/ i reports/descartades/")
    with tempfile.TemporaryDirectory() as tmp:
        reports = Path(tmp) / "reports"
        reports.mkdir()
        (reports / "candidates-a.yaml").write_text(
            "- target: \"I00010\"\n  accept: false\n", encoding="utf-8"
        )
        discarded = reports / "descartades"
        discarded.mkdir()
        (discarded / "candidates-b.yaml").write_text(
            "- target: \"I00020\"\n  accept: false\n", encoding="utf-8"
        )
        # A pending entry, still in the open file, must not be treated as rejected.
        (reports / "candidates-c.yaml").write_text(
            "- target: \"I00030\"\n  accept: null\n", encoding="utf-8"
        )

        rejected = research.previously_rejected(reports)
        check("I00010" in rejected, "una rebutjada encara oberta es troba")
        check("I00020" in rejected, "una rebutjada ja arxivada a descartades/ es troba també")
        check("I00030" not in rejected, "una pendent no compta com a rebutjada")


def main() -> int:
    test_split_three_ways()
    test_research_reads_both_folders()

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

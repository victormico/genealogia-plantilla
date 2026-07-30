"""Move the proposals that are already in the GEDCOM out of the review files.

`reports/*.yaml` only ever grow. An entry marked `accept: true` has been written
to the tree and will never be looked at again, but it stays in the file and
buries the handful that still need a decision -- and a file that is *all*
`accept: true` looks exactly like one that is ready to run. Passing that to
tools.apply or tools.correct a second time inserts every line again.

So the applied entries move to `reports/aplicades/`, keeping the file's own
comments with them. These files are documents as much as data: the reasoning is
in the comments, and PyYAML would throw all of it away on a round-trip. The split
is therefore done on the text, entry by entry, and the result is checked by
parsing both halves and comparing them with the original.

Two things deliberately stay where they are:

  accept: false   A rejection is a decision. tools.research reads it from
                  `reports/candidates-*.yaml` so that somebody refuted by a
                  parish record is not proposed again next week; it does not
                  look inside the archive.
  accept: null    Still to decide. That is the whole point of the exercise.

    python3 -m tools.archive           # dry run
    python3 -m tools.archive --write
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

from .config import tree_path

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
ARCHIVE = REPORTS / "aplicades"

ENTRY = re.compile(r"^-\s")
COMMENT_OR_BLANK = re.compile(r"^\s*(#.*)?$")
SEPARATOR = re.compile(r"^#\s*-{3,}")


def split_entries(text: str) -> tuple[str, list[str]]:
    """The file's header, then one chunk of text per top-level entry.

    A run of comment and blank lines immediately above an entry belongs to that
    entry: in these files it is the section heading («-- l'implexe») or the
    reasoning for the proposal right below it.
    """
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if ENTRY.match(line)]
    if not starts:
        return text, []

    def claim(start: int, floor: int) -> int:
        """How far above `start` the entry's own comments reach."""
        i = start
        while i - 1 >= floor and COMMENT_OR_BLANK.match(lines[i - 1]):
            i -= 1
        return i

    def claim_heading(start: int) -> int:
        """For the first entry: its «-- section --» rule, if it has one.

        Everything else above it is the file header, which both halves keep.
        """
        i = start
        while i - 1 >= 0 and not lines[i - 1].strip():
            i -= 1
        if i - 1 < 0 or not SEPARATOR.match(lines[i - 1]):
            return start
        while i - 1 >= 0 and SEPARATOR.match(lines[i - 1]):
            i -= 1
        return i

    bounds: list[tuple[int, int]] = []
    floor = 0
    for n, start in enumerate(starts):
        # Everything above the *first* entry is the file's header, and it has to
        # stay with both halves -- all but its own section rule. From the second
        # entry on, the unindented comment run above it is its heading.
        top = claim_heading(start) if n == 0 else claim(start, floor)
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        bounds.append((top, end))
        floor = end
    # Each entry ends where the next one's comments begin.
    for n in range(len(bounds) - 1):
        bounds[n] = (bounds[n][0], bounds[n + 1][0])

    header = "\n".join(lines[: bounds[0][0]])
    chunks = ["\n".join(lines[a:b]) for a, b in bounds]
    return header, chunks


def accept_of(chunk: str):
    """The `accept:` value of a single entry, by parsing just that entry."""
    parsed = yaml.safe_load(chunk)
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise ValueError(f"no és una entrada sola:\n{chunk[:200]}")
    return parsed[0].get("accept")


def note(lines: list[str]) -> str:
    return "\n".join(f"# {line}".rstrip() for line in lines)


def rebuild(header: str, chunks: list[str], preamble: str) -> str:
    body = "\n".join(chunks).rstrip("\n")
    parts = [preamble, header.strip("\n"), body]
    return "\n\n".join(p for p in parts if p) + "\n"


def plan_file(path: Path, stamp: str) -> dict | None:
    text = path.read_text(encoding="utf-8")
    original = yaml.safe_load(text) or []
    if not original:
        return None
    # A file can be archived more than once: accept three today, three next week.
    # The archive has to GROW. Writing it fresh would silently throw away
    # everything filed there before.
    prior_path = ARCHIVE / path.name
    prior_text = prior_path.read_text(encoding="utf-8") if prior_path.exists() else ""
    prior = yaml.safe_load(prior_text) or [] if prior_text else []
    header, chunks = split_entries(text)
    if len(chunks) != len(original):
        raise ValueError(
            f"{path.name}: {len(chunks)} blocs de text per {len(original)} entrades; "
            "no es toca"
        )
    done = [c for c in chunks if accept_of(c) is True]
    keep = [c for c in chunks if accept_of(c) is not True]
    if not done:
        return None

    if prior:
        archived = (
            prior_text.rstrip("\n")
            + "\n\n"
            + note([f"Afegit el {stamp}, d'una segona passada sobre reports/{path.name}."])
            + "\n\n"
            + "\n".join(done).rstrip("\n")
            + "\n"
        )
    else:
        archived = rebuild(
            header,
            done,
            note(
                [
                    f"ARXIU ({stamp}). Aquestes entrades ja són a «{tree_path().name}».",
                    "",
                    "No les tornis a passar per tools.apply ni tools.correct: hi tornarien a",
                    "inserir les mateixes línies. Són aquí per saber d'on ve cada cosa.",
                ]
                + (
                    [
                        "",
                        f"El que d'aquest fitxer espera decisió és a reports/{path.name}.",
                    ]
                    if keep
                    else []
                )
            ),
        )
    remaining = (
        rebuild(
            header,
            keep,
            note(
                [
                    f"Les entrades d'aquest fitxer que ja són al GEDCOM s'han mogut a",
                    f"reports/aplicades/{path.name} ({stamp}).",
                    "",
                    "Aquí queda només el que espera decisió, i les propostes descartades,",
                    "que han de continuar en aquesta carpeta perquè tools.research les llegeix.",
                ]
            ),
        )
        if keep
        else None
    )

    # The split has to be lossless: same entries, same order, nothing invented,
    # and whatever was already in the archive still there.
    check = (yaml.safe_load(archived) or []) + (
        yaml.safe_load(remaining) or [] if remaining else []
    )
    expected = (
        list(prior)
        + [e for e in original if e.get("accept") is True]
        + [e for e in original if e.get("accept") is not True]
    )
    if check != expected:
        raise ValueError(f"{path.name}: la divisió no quadra amb l'original; no es toca")

    return {
        "path": path,
        "archived": archived,
        "remaining": remaining,
        "done": len(done),
        "keep": len(keep),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", default=REPORTS, type=Path)
    parser.add_argument("--write", action="store_true", help="actually move things")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%d-%m-%Y")
    plans = []
    for path in sorted(Path(args.reports).glob("*.yaml")):
        try:
            plan = plan_file(path, stamp)
        except ValueError as exc:
            print(f"ATURAT: {exc}", file=sys.stderr)
            return 1
        if plan:
            plans.append(plan)

    if not plans:
        print("res per arxivar: cap fitxer amb entrades ja aplicades")
        return 0

    for plan in plans:
        name = plan["path"].name
        if plan["remaining"]:
            print(f"  {name}: {plan['done']} aplicades -> aplicades/, {plan['keep']} hi queden")
        else:
            print(f"  {name}: {plan['done']} aplicades -> aplicades/, el fitxer sencer")

    if not args.write:
        print("\nassaig en sec — cal --write per moure-ho")
        return 0

    ARCHIVE.mkdir(exist_ok=True)
    for plan in plans:
        path: Path = plan["path"]
        (ARCHIVE / path.name).write_text(plan["archived"], encoding="utf-8")
        if plan["remaining"]:
            path.write_text(plan["remaining"], encoding="utf-8")
        else:
            path.unlink()
    print(f"\n{len(plans)} fitxer(s) arxivat(s) a {ARCHIVE.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

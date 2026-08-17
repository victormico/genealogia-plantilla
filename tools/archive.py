"""Move decided proposals out of the review files.

`reports/*.yaml` only ever grow. An entry marked `accept: true` has been written
to the tree and will never be looked at again, but it stays in the file and
buries the handful that still need a decision -- and a file that is *all*
`accept: true` looks exactly like one that is ready to run. Passing that to
tools.apply or tools.correct a second time inserts every line again. The same
is true, for a different reason, of `accept: false`: a rejection is a decision
too, and once it has been read it just clutters the file that's meant to hold
what's still open.

So `accept: true` entries move to `reports/aplicades/` and `accept: false`
entries move to `reports/descartades/`, each keeping the file's own comments
with them. These files are documents as much as data: the reasoning is in the
comments, and PyYAML would throw all of it away on a round-trip. The split is
therefore done on the text, entry by entry, and the result is checked by
parsing all the pieces and comparing them with the original.

Only one thing deliberately stays where it is: `accept: null`, still to
decide. That is the whole point of the exercise.

A rejection moving to `reports/descartades/` does not stop being read:
`tools.research` scans both `reports/candidates-*.yaml` and
`reports/descartades/candidates-*.yaml` for `accept: false` so that somebody
refuted by a parish record is not proposed again next week; it does not look
inside `reports/aplicades/`.

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
DISCARDED = REPORTS / "descartades"

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
    # Each destination has to GROW. Writing it fresh would silently throw away
    # everything filed there before.
    prior_archive_path = ARCHIVE / path.name
    prior_archive_text = (
        prior_archive_path.read_text(encoding="utf-8") if prior_archive_path.exists() else ""
    )
    prior_archive = yaml.safe_load(prior_archive_text) or [] if prior_archive_text else []
    prior_discard_path = DISCARDED / path.name
    prior_discard_text = (
        prior_discard_path.read_text(encoding="utf-8") if prior_discard_path.exists() else ""
    )
    prior_discard = yaml.safe_load(prior_discard_text) or [] if prior_discard_text else []

    header, chunks = split_entries(text)
    if len(chunks) != len(original):
        raise ValueError(
            f"{path.name}: {len(chunks)} blocs de text per {len(original)} entrades; "
            "no es toca"
        )
    done = [c for c in chunks if accept_of(c) is True]
    discarded = [c for c in chunks if accept_of(c) is False]
    keep = [c for c in chunks if not (accept_of(c) is True or accept_of(c) is False)]
    if not done and not discarded:
        return None

    archived = None
    if done:
        if prior_archive_text:
            archived = (
                prior_archive_text.rstrip("\n")
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

    discarded_text = None
    if discarded:
        if prior_discard_text:
            discarded_text = (
                prior_discard_text.rstrip("\n")
                + "\n\n"
                + note([f"Afegit el {stamp}, d'una segona passada sobre reports/{path.name}."])
                + "\n\n"
                + "\n".join(discarded).rstrip("\n")
                + "\n"
            )
        else:
            discarded_text = rebuild(
                header,
                discarded,
                note(
                    [
                        f"DESCARTADES ({stamp}). Propostes amb `accept: false`, tretes de",
                        f"reports/{path.name}.",
                        "",
                        "`tools.research` les llegeix d'ací (a més de reports/candidates-*.yaml)",
                        "per no tornar a proposar algú que ja s'ha dit que no.",
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

    remaining_note: list[str] = []
    if done:
        remaining_note += [
            "Les entrades d'aquest fitxer que ja són al GEDCOM s'han mogut a",
            f"reports/aplicades/{path.name} ({stamp}).",
        ]
    if discarded:
        if remaining_note:
            remaining_note.append("")
        remaining_note += [
            "Les propostes descartades (`accept: false`) s'han mogut a",
            f"reports/descartades/{path.name} ({stamp}).",
        ]
    remaining_note += ["", "Aquí queda només el que espera decisió."]
    remaining = rebuild(header, keep, note(remaining_note)) if keep else None

    # The split has to be lossless: same entries, same order, nothing invented,
    # and whatever was already filed away still there. Only checked for the
    # pieces this run actually writes.
    check: list = []
    expected: list = []
    if done:
        check += yaml.safe_load(archived) or []
        expected += list(prior_archive) + [e for e in original if e.get("accept") is True]
    if discarded:
        check += yaml.safe_load(discarded_text) or []
        expected += list(prior_discard) + [e for e in original if e.get("accept") is False]
    if keep:
        check += yaml.safe_load(remaining) or []
        expected += [
            e for e in original if not (e.get("accept") is True or e.get("accept") is False)
        ]
    if check != expected:
        raise ValueError(f"{path.name}: la divisió no quadra amb l'original; no es toca")

    return {
        "path": path,
        "archived": archived,
        "discarded": discarded_text,
        "remaining": remaining,
        "done": len(done),
        "discarded_n": len(discarded),
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
        print("res per arxivar: cap fitxer amb entrades ja aplicades o descartades")
        return 0

    for plan in plans:
        name = plan["path"].name
        bits = []
        if plan["done"]:
            bits.append(f"{plan['done']} aplicades -> aplicades/")
        if plan["discarded_n"]:
            bits.append(f"{plan['discarded_n']} descartades -> descartades/")
        tail = f"{plan['keep']} hi queden" if plan["remaining"] else "el fitxer sencer mogut"
        print(f"  {name}: {', '.join(bits)}, {tail}")

    if not args.write:
        print("\nassaig en sec — cal --write per moure-ho")
        return 0

    if any(plan["archived"] for plan in plans):
        ARCHIVE.mkdir(exist_ok=True)
    if any(plan["discarded"] for plan in plans):
        DISCARDED.mkdir(exist_ok=True)
    for plan in plans:
        path: Path = plan["path"]
        if plan["archived"]:
            (ARCHIVE / path.name).write_text(plan["archived"], encoding="utf-8")
        if plan["discarded"]:
            (DISCARDED / path.name).write_text(plan["discarded"], encoding="utf-8")
        if plan["remaining"]:
            path.write_text(plan["remaining"], encoding="utf-8")
        else:
            path.unlink()
    print(f"\n{len(plans)} fitxer(s) tocats a {REPORTS.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

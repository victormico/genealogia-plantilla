"""Apply reviewed corrections to the canonical GEDCOM.

This is the one place in the toolchain that is **not** additive. Everything else
only ever inserts lines, which is what makes a `git diff` proof that nothing was
disturbed. Correcting a wrong date or a misspelt surname means replacing a line,
so the diff will show deletions for the first time.

That is why every edit here is guarded. Each one names the exact line it expects
to find, and the run refuses outright if that line is absent, or if it appears
more than once inside the record. A correction that cannot be located precisely
is not applied at all -- it is never guessed at.

Three kinds of edit:

    find / replace   one line, given verbatim, swapped for another
    insert / before  one or more lines spliced in ahead of a named line
    delete           a contiguous block of lines, every one given verbatim

`delete` is the sharpest tool in the box and carries an extra guard the others
do not need. In GEDCOM a line owns the deeper lines that follow it, so removing
`3 MAP` while leaving `4 LATI` behind does not lose data -- it corrupts the
file, and quietly, because the orphan re-attaches itself to whatever sits
above. So a delete must remove *whole subtrees*: the block has to begin at its
own shallowest level, and the line after it may not be deeper than that. If the
cut would strand a child, the run refuses.

    python3 -m tools.correct reports/correccions.yaml            # dry run
    python3 -m tools.correct reports/correccions.yaml --write
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from difflib import unified_diff
from pathlib import Path

import yaml

from .config import tree_path
from .gedcom.lines import SOSA_TAG, GedcomFile, dedupe_sosa
from .apply import accepted, validate

ROOT = Path(__file__).resolve().parents[1]


class Refused(Exception):
    """A guard failed. Nothing is written when this is raised."""


def _record_range(ged: GedcomFile, xref: str) -> tuple[int, int]:
    rec = ged.by_xref.get(xref)
    if rec is None:
        raise Refused(f"@{xref}@ no existeix a {ged.path.name}")
    return rec.start, rec.end


def _locate(ged: GedcomFile, xref: str, text: str) -> int:
    """The single line index inside the record whose raw text equals `text`."""
    start, end = _record_range(ged, xref)
    hits = [i for i in range(start, end) if ged.raw[i] == text]
    if not hits:
        raise Refused(f"@{xref}@: no s'hi troba la línia {text!r}")
    if len(hits) > 1:
        raise Refused(
            f"@{xref}@: la línia {text!r} hi surt {len(hits)} vegades; "
            "no es pot corregir sense ambigüitat"
        )
    return hits[0]


def _locate_block(ged: GedcomFile, xref: str, block: list[str]) -> int:
    """Index of the one place inside the record where `block` appears in a row.

    Every line must be given verbatim, and the run refuses if the block appears
    nowhere or more than once -- the same rule as `find`, extended to a run of
    lines so that a delete cannot be aimed by guesswork.
    """
    if not block:
        raise Refused(f"@{xref}@: un 'delete' buit no vol dir res")
    start, end = _record_range(ged, xref)
    hits = [
        i
        for i in range(start, end - len(block) + 1)
        if ged.raw[i : i + len(block)] == block
    ]
    if not hits:
        raise Refused(
            f"@{xref}@: no s'hi troba el bloc {block!r} tal com està escrit. "
            "Les línies s'han de donar literals i seguides"
        )
    if len(hits) > 1:
        raise Refused(
            f"@{xref}@: el bloc {block!r} hi surt {len(hits)} vegades; "
            "no es pot esborrar sense ambigüitat"
        )
    return hits[0]


def _refuse_if_it_orphans(ged: GedcomFile, xref: str, i: int, block: list[str]) -> None:
    """The structural guard: a delete must take whole subtrees, never half of one."""
    levels = []
    for offset in range(len(block)):
        line = ged.lines[i + offset]
        if line is None:
            raise Refused(f"@{xref}@: la línia {i + offset + 1} no és una línia GEDCOM")
        if line.level == 0:
            raise Refused(
                f"@{xref}@: {block[offset]!r} és de nivell 0. "
                "Aquesta eina no esborra registres sencers"
            )
        if line.tag == "CHAN" or (line.level > 1 and line.tag in ("DATE", "TIME")
                                  and _inside_chan(ged, xref, i + offset)):
            raise Refused(
                f"@{xref}@: {block[offset]!r} forma part del CHAN, "
                "que és el que marca la data de modificació. No es toca"
            )
        levels.append(line.level)

    top = min(levels)
    if levels[0] != top:
        raise Refused(
            f"@{xref}@: el bloc comença per {block[0]!r}, que és més profund que "
            f"{block[levels.index(top)]!r}. Un delete ha de començar pel nivell més alt"
        )
    after = ged.lines[i + len(block)] if i + len(block) < len(ged.lines) else None
    if after is not None and after.level > top:
        raise Refused(
            f"@{xref}@: esborrar aquest bloc deixaria orfe "
            f"{ged.raw[i + len(block)]!r}, que hi penja a sota. "
            "Cal incloure-la al delete o no esborrar el pare"
        )


def _inside_chan(ged: GedcomFile, xref: str, i: int) -> bool:
    start, _ = _record_range(ged, xref)
    for j in range(i - 1, start - 1, -1):
        line = ged.lines[j]
        if line is None:
            continue
        if line.level <= 1:
            return line.tag == "CHAN"
    return False


def plan(ged: GedcomFile, entries: list[dict], stamp_date: str, stamp_time: str):
    """Work out every line change. Raises Refused before touching anything."""
    replacements: dict[int, str] = {}
    insertions: dict[int, list[str]] = {}
    deletions: set[int] = set()
    touched: list[str] = []
    log: list[str] = []

    for entry in accepted(entries):
        xref = str(entry["target"]).strip("@")
        edits = entry.get("edits") or []
        if not edits:
            raise Refused(f"@{xref}@: la proposta no porta cap 'edits'")
        for edit in edits:
            if "find" in edit:
                i = _locate(ged, xref, edit["find"])
                if i in replacements:
                    raise Refused(f"@{xref}@: dues correccions a la mateixa línia {i + 1}")
                replacements[i] = edit["replace"]
                log.append(f"  @{xref}@ l.{i + 1}  {edit['find']!r} -> {edit['replace']!r}")
            elif "insert" in edit:
                i = _locate(ged, xref, edit["before"])
                # A single line or a whole block: inserting `1 BIRT` on its own
                # would be meaningless, so a list has to be allowed.
                block = edit["insert"]
                lines = [block] if isinstance(block, str) else list(block)
                insertions.setdefault(i, []).extend(lines)
                for line in lines:
                    log.append(f"  @{xref}@ l.{i + 1}  + {line!r}")
            elif "delete" in edit:
                block = edit["delete"]
                lines = [block] if isinstance(block, str) else list(block)
                i = _locate_block(ged, xref, lines)
                _refuse_if_it_orphans(ged, xref, i, lines)
                for offset, line in enumerate(lines):
                    j = i + offset
                    if j in replacements or j in insertions:
                        raise Refused(
                            f"@{xref}@: la línia {j + 1} s'esborra i alhora es "
                            "corregeix o s'hi insereix; decidiu-vos"
                        )
                    deletions.add(j)
                    log.append(f"  @{xref}@ l.{j + 1}  - {line!r}")
            else:
                raise Refused(
                    f"@{xref}@: un 'edit' ha de portar 'find', 'insert' o 'delete'"
                )
        touched.append(xref)

    # Ancestris stamps every record it changes. A corrected record whose CHAN
    # still says last September would misrepresent when the data was touched.
    for xref in touched:
        start, end = _record_range(ged, xref)
        chan = [i for i in range(start, end) if ged.raw[i] == "1 CHAN"]
        if not chan:
            log.append(f"  @{xref}@: sense CHAN, no s'hi posa data de modificació")
            continue
        for i in range(chan[0] + 1, end):
            line = ged.lines[i]
            if line is None or line.level <= 1:
                break
            if line.tag == "DATE" and i not in replacements:
                replacements[i] = f"2 DATE {stamp_date}"
            elif line.tag == "TIME" and i not in replacements:
                replacements[i] = f"3 TIME {stamp_time}"

    return replacements, insertions, deletions, touched, log


def render(
    ged: GedcomFile,
    replacements: dict[int, str],
    insertions: dict[int, list[str]],
    deletions: set[int] = frozenset(),
):
    out: list[str] = []
    for i, raw in enumerate(ged.raw):
        out.extend(insertions.get(i, ()))
        if i in deletions:
            continue
        out.append(replacements.get(i, raw))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_file")
    parser.add_argument("--gedcom", default=None)
    parser.add_argument("--write", action="store_true", help="actually modify the file")
    args = parser.parse_args()

    path = Path(args.review_file)
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    validate(entries)
    ok = accepted(entries)
    pending = sum(1 for e in entries if e.get("accept") is None)
    rejected = sum(1 for e in entries if e.get("accept") is False)
    print(
        f"{path.name}: {len(entries)} correccions — {len(ok)} acceptades, "
        f"{rejected} descartades, {pending} pendents"
    )
    if not ok:
        print("res acceptat, res a fer")
        return 0

    ged = GedcomFile(args.gedcom or tree_path())
    now = datetime.now()
    try:
        replacements, insertions, deletions, touched, log = plan(
            ged, entries, now.strftime("%d %b %Y").upper(), now.strftime("%H:%M:%S")
        )
    except Refused as exc:
        print(f"\nATURAT, no s'ha escrit res:\n  {exc}", file=sys.stderr)
        return 1

    for line in log:
        print(line)
    # Compared with the Ancestris d'Aboville duplicates already gone from both
    # sides, so the counts below describe THIS correction and not the cleanup
    # that `write` does regardless. The cleanup gets its own line.
    before, dropped = dedupe_sosa(ged.raw)
    after, _ = dedupe_sosa(render(ged, replacements, insertions, deletions))
    if dropped:
        print(f"  {len(dropped)} línia/es {SOSA_TAG} duplicada/es que s'esborraran en desar")

    diff = list(
        unified_diff(before, after, fromfile=f"a/{ged.path.name}", tofile=f"b/{ged.path.name}", n=1, lineterm="")
    )
    changed = sum(1 for d in diff if d.startswith(("+", "-")) and not d.startswith(("+++", "---")))
    print(f"\n{len(touched)} registres, {len(replacements)} línies substituïdes, "
          f"{sum(len(v) for v in insertions.values())} inserides, "
          f"{len(deletions)} esborrades ({changed} línies al diff)")

    if not args.write:
        print("assaig en sec — cal --write per aplicar-ho")
        return 0

    stamp = now.strftime("%Y%m%d-%H%M%S")
    backup = ged.path.with_name(f"{ged.path.stem}_{stamp}{ged.path.suffix}")
    shutil.copy2(ged.path, backup)
    ged.write(ged.path, after)
    print(f"escrit {ged.path.name}; la versió anterior queda com a {backup.name}")

    reread = GedcomFile(ged.path)
    print(f"rellegit: {len(reread.raw)} línies (abans {len(before)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

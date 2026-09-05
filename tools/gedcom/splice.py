"""Append-only editing of a GEDCOM file.

Two operations only, both additive:

  * `append_record`  -- a new `0 @Innn@ INDI` / `FAM` / `SOUR` block, inserted
    immediately before `0 TRLR`.
  * `insert_into`    -- extra subordinate lines inside an existing record,
    placed before its `1 CHAN` line (Ancestris keeps CHAN last). `add_lines`
    is the same thing for a record that may instead have been appended
    earlier in this same run.

Nothing is ever deleted or rewritten. Every untouched line keeps its exact
bytes, so `git diff` on the result shows only the intended additions — which is
the real safety net, and it only works because we never reformat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .lines import GedcomFile


@dataclass
class _Insertion:
    at: int  # insert before this raw-line index
    lines: list[str]
    why: str  # short description, for the change log


@dataclass
class Splicer:
    """Collects additions, then applies them all at once."""

    ged: GedcomFile
    _insertions: list[_Insertion] = field(default_factory=list)
    _new_xrefs: dict[str, int] = field(default_factory=dict)

    # -- xref allocation --------------------------------------------------

    def reserve_xref(self, prefix: str) -> str:
        """Allocate the next free xref, accounting for ones reserved this run."""
        base = self.ged.max_xref(prefix)
        used = self._new_xrefs.get(prefix, base)
        nxt = used + 1
        self._new_xrefs[prefix] = nxt
        return f"{prefix}{nxt:05d}"

    # -- the two operations -----------------------------------------------

    def append_record(self, lines: list[str], why: str = "") -> None:
        """Add a complete level-0 record before `0 TRLR`."""
        if not lines or not lines[0].startswith("0 "):
            raise ValueError(f"append_record needs a level-0 block, got: {lines[:1]}")
        self._insertions.append(_Insertion(self.ged.trlr_index(), list(lines), why))

    def insert_into(self, xref: str, lines: list[str], why: str = "") -> None:
        """Add subordinate lines to an existing record, before its `1 CHAN`."""
        rec = self.ged.by_xref.get(xref)
        if rec is None:
            raise KeyError(f"no record @{xref}@ in {self.ged.path.name}")
        chan = self.ged.sub(xref, "CHAN")
        at = chan[0].index if chan else rec.end
        self._insertions.append(_Insertion(at, list(lines), why))

    def add_lines(self, xref: str, lines: list[str], why: str = "") -> None:
        """`insert_into`, but a record queued this run counts as existing too.

        `insert_into` can only reach what the file already has. A record
        appended earlier in the same run is not in `by_xref` yet, so asking for
        it there raises -- and the caller's way around that was to write the
        pointer on one side only. That is how a person could end up named by a
        family that they did not name back.

        Lines folded into a queued record are counted under that record's own
        changelog entry, so `why` is only used when the record is already on
        disk. Nothing is lost from the diff -- only from the running commentary.
        """
        if xref in self.ged.by_xref:
            self.insert_into(xref, lines, why)
            return
        head = f"0 @{xref}@ "
        for ins in self._insertions:
            if ins.lines and ins.lines[0].startswith(head):
                # Before its CHAN, same as insert_into: Ancestris keeps CHAN last.
                at = next(
                    (n for n, line in enumerate(ins.lines) if line == "1 CHAN"),
                    len(ins.lines),
                )
                ins.lines[at:at] = list(lines)
                return
        raise KeyError(
            f"no record @{xref}@ in {self.ged.path.name}, nor queued this run"
        )

    # -- application ------------------------------------------------------

    @property
    def pending(self) -> int:
        return len(self._insertions)

    def changelog(self) -> list[str]:
        return [f"{ins.why} ({len(ins.lines)} lines)" for ins in self._insertions]

    def apply(self) -> list[str]:
        """Return the new raw line list. Does not touch the original file."""
        out: list[str] = []
        # Group by position and apply back-to-front-safe: build by walking once.
        by_pos: dict[int, list[str]] = {}
        for ins in self._insertions:
            by_pos.setdefault(ins.at, []).extend(ins.lines)
        for i, raw in enumerate(self.ged.raw):
            out.extend(by_pos.get(i, ()))
            out.append(raw)
        # Anything targeting a position past the last line (rec.end == len(raw)).
        for pos in sorted(p for p in by_pos if p >= len(self.ged.raw)):
            out.extend(by_pos[pos])
        return out

    def write(self, path: str | Path) -> Path:
        return self.ged.write(path, self.apply())

    def write_timestamped(self, stamp: str) -> Path:
        """Write beside the source using Ancestris' `name_YYYYMMDD-HHMMSS.ged`.

        `stamp` is passed in rather than read from the clock so callers stay
        deterministic and testable.
        """
        src = self.ged.path
        return self.write(src.with_name(f"{src.stem}_{stamp}{src.suffix}"))

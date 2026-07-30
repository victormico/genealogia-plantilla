"""Byte-preserving line-level access to a GEDCOM 5.5.1 file.

No GEDCOM library round-trips bytes: they all parse into an object model and
re-serialise, which would destroy this file's BOM, its `_SOSADABOVILLE` tags,
the six-level Catalan PLAC format, the zero-padded xref numbering and the four
`SURN` values that carry a trailing space.

So this module never reconstructs a line. It keeps every line exactly as read
and parses *alongside* the raw text, never in place of it. Writing back out is
`BOM + newline.join(raw)`, which is byte-identical by construction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BOM = "﻿"

# Ancestris writes surnames in the canonical file in caps; a handful carry a
# trailing space. Values are compared with this stripped, never rewritten.
_XREF_RE = re.compile(r"^@([^@]+)@$")


@dataclass(frozen=True)
class Line:
    """One parsed GEDCOM line. `raw` is authoritative; the rest is derived."""

    index: int  # 0-based position in GedcomFile.raw
    level: int
    xref: str | None  # record identifier, e.g. "I00001" (without @)
    tag: str
    value: str  # "" when the line has no value; never None
    raw: str

    @property
    def pointer(self) -> str | None:
        """The xref this line points *to*, e.g. "F00002" for `1 FAMC @F00002@`."""
        m = _XREF_RE.match(self.value.strip())
        return m.group(1) if m else None


@dataclass(frozen=True)
class Record:
    """A top-level (level 0) record and the span of lines it owns."""

    xref: str | None  # None for HEAD and TRLR
    tag: str  # INDI, FAM, SOUR, NOTE, SUBM, HEAD, TRLR
    start: int  # index of the `0 ...` line
    end: int  # index one past the last line of the record


def _parse(index: int, raw: str) -> Line | None:
    """Split `level [@xref@] tag [value]`. Returns None for blank lines."""
    stripped = raw.strip()
    if not stripped:
        return None
    parts = raw.split(" ")
    try:
        level = int(parts[0])
    except ValueError:
        # Not a conforming GEDCOM line. Keep it verbatim, expose it as level -1
        # so callers can notice rather than silently mis-index it.
        return Line(index, -1, None, "", raw, raw)
    i = 1
    xref = None
    if i < len(parts):
        m = _XREF_RE.match(parts[i])
        if m:
            xref = m.group(1)
            i += 1
    tag = parts[i] if i < len(parts) else ""
    i += 1
    value = " ".join(parts[i:]) if i < len(parts) else ""
    return Line(index, level, xref, tag, value, raw)


class GedcomFile:
    """A GEDCOM file held as raw lines, with a parsed index over them."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        data = self.path.read_text(encoding="utf-8")
        self.has_bom = data.startswith(BOM)
        if self.has_bom:
            data = data[len(BOM) :]
        # Ancestris writes LF and a trailing newline. Detect rather than assume.
        self.newline = "\r\n" if "\r\n" in data else "\n"
        self.trailing_newline = data.endswith(self.newline)
        if self.trailing_newline:
            data = data[: -len(self.newline)]
        self.raw: list[str] = data.split(self.newline)

        self.lines: list[Line | None] = [_parse(i, r) for i, r in enumerate(self.raw)]
        self.records: list[Record] = self._index_records()
        self.by_xref: dict[str, Record] = {
            r.xref: r for r in self.records if r.xref is not None
        }

    # -- indexing ---------------------------------------------------------

    def _index_records(self) -> list[Record]:
        starts = [ln.index for ln in self.lines if ln and ln.level == 0]
        out: list[Record] = []
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(self.raw)
            ln = self.lines[start]
            assert ln is not None
            out.append(Record(xref=ln.xref, tag=ln.tag, start=start, end=end))
        return out

    def record_lines(self, xref: str) -> list[Line]:
        """Every parsed line of a record, including its `0 ...` header line."""
        rec = self.by_xref[xref]
        return [ln for ln in self.lines[rec.start : rec.end] if ln is not None]

    def of_type(self, tag: str) -> list[Record]:
        return [r for r in self.records if r.tag == tag]

    # -- queries ----------------------------------------------------------

    def sub(self, xref: str, tag: str, level: int = 1) -> list[Line]:
        """Direct children of a record with the given tag at the given level."""
        return [
            ln for ln in self.record_lines(xref) if ln.level == level and ln.tag == tag
        ]

    def value(self, xref: str, tag: str, level: int = 1) -> str | None:
        """First value for a tag, whitespace-stripped. None if absent."""
        found = self.sub(xref, tag, level)
        return found[0].value.strip() if found else None

    def nested(self, parent: Line, tag: str, xref: str) -> Line | None:
        """First child of `parent` with `tag`, searched within record `xref`.

        Children are the lines following `parent` at exactly parent.level + 1,
        stopping at the first line back at parent.level or shallower.
        """
        rec = self.by_xref[xref]
        for ln in self.lines[parent.index + 1 : rec.end]:
            if ln is None:
                continue
            if ln.level <= parent.level:
                break
            if ln.level == parent.level + 1 and ln.tag == tag:
                return ln
        return None

    def trlr_index(self) -> int:
        """Index of the `0 TRLR` line. New records are appended before it."""
        for r in self.records:
            if r.tag == "TRLR":
                return r.start
        raise ValueError(f"{self.path}: no 0 TRLR line; refusing to write")

    def max_xref(self, prefix: str) -> int:
        """Highest numeric suffix among xrefs starting with `prefix` ("I", "F", "S")."""
        best = 0
        pat = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        for xref in self.by_xref:
            m = pat.match(xref)
            if m:
                best = max(best, int(m.group(1)))
        return best

    def next_xref(self, prefix: str, width: int = 5) -> str:
        """Next free xref in the file's zero-padded style, e.g. "I00176"."""
        return f"{prefix}{self.max_xref(prefix) + 1:0{width}d}"

    # -- output -----------------------------------------------------------

    def render(self, raw: list[str] | None = None) -> str:
        """Reassemble the file text. With no argument this is byte-identical."""
        body = self.newline.join(self.raw if raw is None else raw)
        return (BOM if self.has_bom else "") + body + (
            self.newline if self.trailing_newline else ""
        )

    def write(self, path: str | Path, raw: list[str] | None = None) -> Path:
        out = Path(path)
        out.write_text(self.render(raw), encoding="utf-8", newline="")
        return out

    def __repr__(self) -> str:
        counts = {}
        for r in self.records:
            counts[r.tag] = counts.get(r.tag, 0) + 1
        summary = " ".join(f"{t}={n}" for t, n in sorted(counts.items()))
        return f"<GedcomFile {self.path.name} lines={len(self.raw)} {summary}>"

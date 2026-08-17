"""An import-ready copy of the GEDCOM for obsidian-charted-roots.

The canonical file keeps the six-level Catalan PLAC format that Ancestris
declares in the header:

    2 FORM Aldea, Ciutat, Codi Postal, Comtat, Estat, País
    2 PLAC , Jorquera, 02041, Albacete, Castella i la Manxa, Espanya

That format is *positional*: an empty slot means "this level doesn't apply", so
the leading comma is data, not a typo, and the empty slots cannot be dropped
from the tree without shifting every place one level up.

Charted Roots 0.22.76 ignores `PLAC.FORM` and just splits on commas. Two things
follow, and both are fixed here rather than upstream:

1. It copies the raw PLAC string into frontmatter unquoted, so
   `spouse1_marriage_location: , Jorquera, ...` is invalid YAML -- a plain
   scalar cannot start with `,`. It writes those notes anyway and only fails
   later, when the citation pass reads one back: "Plain value cannot start with
   flow indicator character".
2. It has no notion of a postal code, so `02041` becomes a jurisdiction of its
   own -- `Places/02041 Albacete.md`, with Jorquera filed under it.

So the export drops the empty slots and the postal code. Nothing Charted Roots
uses is lost -- it already collapses the empty slots when it builds the place
hierarchy -- and the canonical file is untouched.

Usage:

    python -m tools.obsidian                     # writes <arbre> (Obsidian).ged
    python -m tools.obsidian --check             # report what would change, write nothing
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from .config import tree_path
from .gedcom.lines import GedcomFile

_PLAC_RE = re.compile(r"^(?P<prefix>\d+ PLAC )(?P<value>.*)$")

# Position of `Codi Postal` in the header FORM, 0-based. Only checked against
# the FORM actually declared, so a header change is noticed instead of assumed.
_FORM = "Aldea, Ciutat, Codi Postal, Comtat, Estat, País"
_POSTAL_SLOT = 2


def normalise_place(value: str, drop_postal: bool = True) -> str:
    """Collapse a six-level positional PLAC into a plain comma-separated chain.

    >>> normalise_place(", Jorquera, 02041, Albacete, Castella i la Manxa, Espanya")
    'Jorquera, Albacete, Castella i la Manxa, Espanya'
    >>> normalise_place("El Poblet, Fontanars dels Alforins, , Província de València, , Espanya")
    'El Poblet, Fontanars dels Alforins, Província de València, Espanya'
    """
    parts = [p.strip() for p in value.split(",")]
    if drop_postal and len(parts) > _POSTAL_SLOT:
        parts[_POSTAL_SLOT] = ""
    return ", ".join(p for p in parts if p)


def verify_form(gedcom: GedcomFile) -> None:
    """Refuse to guess which slot is the postal code if the FORM ever changes."""
    for line in gedcom.lines:
        if line and line.tag == "FORM" and "Codi Postal" in line.value:
            if line.value.strip() != _FORM:
                raise ValueError(
                    f"header PLAC FORM changed to {line.value.strip()!r}; "
                    f"expected {_FORM!r}. Check _POSTAL_SLOT before exporting."
                )
            return
    raise ValueError("no PLAC FORM in header; refusing to reposition place levels")


def build(gedcom: GedcomFile) -> tuple[list[str], list[tuple[int, str, str]]]:
    """Return the rewritten lines and every (line number, before, after) change."""
    verify_form(gedcom)
    out = list(gedcom.raw)
    changes: list[tuple[int, str, str]] = []
    for i, raw in enumerate(gedcom.raw):
        m = _PLAC_RE.match(raw)
        if not m or not m.group("value").strip():
            continue
        before = m.group("value")
        after = normalise_place(before)
        if after != before:
            out[i] = m.group("prefix") + after
            changes.append((i + 1, before, after))
    return out, changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report what would change and write nothing",
    )
    args = parser.parse_args(argv)

    source = Path(args.source) if args.source else tree_path()
    out_path = Path(args.out) if args.out else source.with_name(f"{source.stem} (Obsidian).ged")

    gedcom = GedcomFile(source)
    out, changes = build(gedcom)

    leading = sum(1 for _, before, _ in changes if before.startswith(","))
    print(f"{len(changes)} PLAC lines rewritten ({leading} started with a comma)")
    for lineno, before, after in changes[:3]:
        print(f"  l.{lineno}: {before}\n       -> {after}")
    if len(changes) > 3:
        print(f"  … and {len(changes) - 3} more")

    still_bad = [
        raw for raw in out if (m := _PLAC_RE.match(raw)) and m.group("value").startswith(",")
    ]
    if still_bad:
        print(f"REFUSING: {len(still_bad)} PLAC values still start with a comma")
        return 1

    if args.check:
        print("--check: nothing written")
        return 0

    path = gedcom.write(out_path, out)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

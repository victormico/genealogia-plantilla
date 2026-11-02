"""Cut one branch out of the tree, for relatives who should only see their part.

A person's branch is their ancestors and every descendant of each of those
ancestors: cousins, uncles and nephews of any degree, which is what somebody on
that side recognises as "their family". The spouses of all of them come along
too, but **without their parents**, who already belong to another branch.

    python -m tools.branca --sosa 11 branca.ged     # by Sosa number
    python -m tools.branca I00011 branca.ged        # by xref

What is outside the branch is not in the file at all -- not hidden, absent.
Families lose their links to whoever is left out, and of the sources, notes and
media objects only the ones somebody inside cites come along (and whatever they
cite in turn: a source brings its repository). That is what makes it safe to
give a portal such as webtrees as a tree of its own and grant somebody access to
that tree only (`tools.portal`).

**Prose is not cut.** If the note of somebody inside the branch talks about
somebody outside it, the name is still written there. Read the notes before
sharing a branch with anybody.

The output carries no BOM: `tree-import` in webtrees 2.2.6 rejects a file that
starts with one, and Ancestris always writes it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import ConfigError, tree_path
from .gedcom.lines import GedcomFile

# Links that make up the family graph. Every other pointer -- SOUR, OBJE, NOTE,
# REPO, SUBM -- is to a record that only comes along if somebody cites it.
GRAPH = {"INDI", "FAM"}


@dataclass
class Branch:
    root: str
    people: set[str] = field(default_factory=set)
    families: set[str] = field(default_factory=set)
    others: set[str] = field(default_factory=set)  # sources, notes, objects…

    def __contains__(self, xref: str) -> bool:
        return xref in self.people or xref in self.families or xref in self.others


def by_sosa(ged: GedcomFile, sosa: int) -> str:
    """The xref labelled with this Sosa number by Ancestris (`_SOSADABOVILLE`)."""
    for rec in ged.of_type("INDI"):
        for ln in ged.sub(rec.xref, "_SOSADABOVILLE"):
            if ln.value.split()[:1] == [str(sosa)]:
                return rec.xref
    raise ConfigError(f"Cap persona de {ged.path.name} no té el Sosa {sosa}.")


def _pointers(ged: GedcomFile, xref: str, tags: set[str] | None = None) -> list[str]:
    return [
        ln.pointer
        for ln in ged.record_lines(xref)[1:]
        if ln.pointer and (tags is None or ln.tag in tags)
    ]


def extract(ged: GedcomFile, root: str) -> Branch:
    """Who and what belongs to the branch of `root`."""
    root = root.strip("@")
    rec = ged.by_xref.get(root)
    if rec is None or rec.tag != "INDI":
        raise ConfigError(f"{root!r} no és cap persona de {ged.path.name}.")

    famc = {r.xref: _pointers(ged, r.xref, {"FAMC"}) for r in ged.of_type("INDI")}
    fams = {r.xref: _pointers(ged, r.xref, {"FAMS"}) for r in ged.of_type("INDI")}
    parents = {r.xref: _pointers(ged, r.xref, {"HUSB", "WIFE"}) for r in ged.of_type("FAM")}
    children = {r.xref: _pointers(ged, r.xref, {"CHIL"}) for r in ged.of_type("FAM")}

    # Ancestors through every filiation, PEDI or not. Deciding which ones count
    # as ancestry is `estat.filiacions_que_compten`'s job, for the numbers; here
    # the question is who a relative would expect to find, and the family that
    # raised a foundling is the only one they will ever have.
    ancestors: set[str] = set()
    pending = [root]
    while pending:
        x = pending.pop()
        if x in ancestors or x not in famc:
            continue
        ancestors.add(x)
        for f in famc[x]:
            pending.extend(parents.get(f, []))

    core: set[str] = set()
    pending = list(ancestors)
    while pending:
        x = pending.pop()
        if x in core or x not in fams:
            continue
        core.add(x)
        for f in fams[x]:
            pending.extend(children.get(f, []))

    branch = Branch(root)
    branch.families = {f for x in core for f in famc[x] + fams[x] if f in parents}
    branch.people = set(core)
    for x in core:
        for f in fams[x]:
            branch.people.update(p for p in parents.get(f, []) if p in famc)

    # Whatever the records inside cite, and whatever that cites in turn. The
    # header counts as inside: it names the submitter.
    for rec in ged.records:
        if rec.tag == "HEAD":
            branch.others.update(
                ln.pointer
                for ln in ged.lines[rec.start : rec.end]
                if ln and ln.pointer in ged.by_xref
            )
    pending = sorted(branch.people | branch.families | branch.others)
    while pending:
        for y in _pointers(ged, pending.pop()):
            target = ged.by_xref.get(y)
            if target and target.tag not in GRAPH and y not in branch:
                branch.others.add(y)
                pending.append(y)
    return branch


def _trim(ged: GedcomFile, start: int, end: int, branch: Branch) -> list[str]:
    """The record's raw lines, without pointers to people or families outside."""
    out: list[str] = []
    skipping: int | None = None
    for ln in ged.lines[start:end]:
        if ln is None:
            continue
        if skipping is not None and ln.level > skipping:
            continue
        skipping = None
        target = ged.by_xref.get(ln.pointer) if ln.pointer else None
        if ln.level > 0 and target and target.tag in GRAPH and ln.pointer not in branch:
            skipping = ln.level  # the pointer and everything under it (PEDI…)
            continue
        out.append(ln.raw)
    return out


def render(ged: GedcomFile, branch: Branch) -> str:
    raw: list[str] = []
    for rec in ged.records:
        if rec.xref is None or rec.xref in branch:
            raw.extend(_trim(ged, rec.start, rec.end, branch))
    return ged.newline.join(raw) + ged.newline


def write(ged: GedcomFile, branch: Branch, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(ged, branch), encoding="utf-8", newline="")
    return out


def summary(ged: GedcomFile, branch: Branch) -> str:
    return (
        f"{len(branch.people)} persones, {len(branch.families)} famílies i "
        f"{len(branch.others)} registres més "
        f"(de {len(ged.of_type('INDI'))} persones a l'arbre sencer)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("arrel", nargs="?", help="xref de la persona d'on parteix la branca")
    parser.add_argument("eixida", help="el GEDCOM retallat que s'escriurà")
    parser.add_argument("--sosa", type=int, help="en lloc del xref, el número de Sosa")
    parser.add_argument("--canonical", default=None, help="el GEDCOM d'entrada")
    args = parser.parse_args(argv)
    if not args.arrel and not args.sosa:
        parser.error("cal un xref o --sosa")

    ged = GedcomFile(args.canonical or tree_path())
    root = by_sosa(ged, args.sosa) if args.sosa else args.arrel
    branch = extract(ged, root)
    out = write(ged, branch, args.eixida)
    print(f"{out}: {summary(ged, branch)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

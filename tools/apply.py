"""Apply reviewed proposals to the canonical GEDCOM. Additive, opt-in, reversible.

Reads a YAML review file, keeps only the entries marked `accept: true`, and
splices them in through tools.gedcom.splice, which can only ever add lines.

Defaults to a dry run that prints the diff. Nothing is written without --write.
When it does write, it follows Ancestris' own convention: the current file is
copied to `<tree>_YYYYMMDD-HHMMSS.ged` and the canonical name gets the new
content, so `git diff` on the canonical file shows exactly what changed.

    python3 -m tools.apply reports/candidates-2026-07-30.yaml            # dry run
    python3 -m tools.apply reports/candidates-2026-07-30.yaml --write    # write
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from difflib import unified_diff
from pathlib import Path

import yaml

from .config import tree_path
from .fs.fetch import LiveTree
from .gedcom.lines import SOSA_TAG, GedcomFile, dedupe_sosa
from .gedcom.splice import Splicer
from .people import load_people
from .render import PlaceBook, render_family, render_individual, render_source

from .config import ROOT
PEDIGREE = ROOT / "cache" / "pedigree.json"


def validate(entries: list[dict]) -> None:
    """Refuse to run if any accept value is not exactly true, false or null.

    A typo like `accept: trueº` parses as a string, which would be silently
    skipped -- the decision would vanish without a word. Anything that is not
    unambiguously a boolean has to stop the run and be pointed at.
    """
    bad = []
    for n, entry in enumerate(entries, start=1):
        for key in ("accept", "accept_ancestors"):
            if key not in entry:
                continue
            value = entry[key]
            if value is not None and not isinstance(value, bool):
                bad.append(
                    f"  proposta {n} ({entry.get('target', '?')}): "
                    f"{key}: {value!r} — ha de ser true, false o null"
                )
    if bad:
        raise SystemExit(
            "valors d'acceptació que no s'entenen; no s'ha escrit res:\n"
            + "\n".join(bad)
        )


def accepted(entries: list[dict]) -> list[dict]:
    """Only entries explicitly accepted. `null`, absent and false are all skipped."""
    return [e for e in entries if e.get("accept") is True]


def apply_fsftid(splicer: Splicer, ged: GedcomFile, entries: list[dict]) -> tuple[int, list[str]]:
    """Splice `1 _FSFTID <pid>` into each accepted person."""
    people = load_people(ged)
    applied, notes = 0, []
    for entry in accepted(entries):
        xref = str(entry["target"]).strip("@")
        pid = str(entry["fsftid"]).strip()
        person = people.get(xref)
        if person is None:
            notes.append(f"skipped {xref}: no such record in {ged.path.name}")
            continue
        if person.fsftid:
            if person.fsftid == pid:
                notes.append(f"skipped @{xref}@: already has _FSFTID {pid}")
            else:
                notes.append(
                    f"SKIPPED @{xref}@ {person.label()}: already has _FSFTID "
                    f"{person.fsftid}, proposal says {pid} — resolve by hand"
                )
            continue
        splicer.insert_into(
            xref, [f"1 _FSFTID {pid}"], why=f"@{xref}@ {person.label()} -> {pid}"
        )
        applied += 1
    return applied, notes


FS_TREE_SOURCE_TITLE = "FamilySearch Family Tree"


FS_TREE_SOURCE = {
    "title": FS_TREE_SOURCE_TITLE,
    "url": "https://www.familysearch.org/tree/",
    "text": (
        "Arbre genealògic col·laboratiu de FamilySearch. L'identificador concret "
        "de cada persona consta a la seva etiqueta _FSFTID; l'adreça és "
        "https://www.familysearch.org/tree/person/details/<id>."
    ),
}


def _source_record(splicer: Splicer, ged: GedcomFile, spec: dict, made: dict) -> str:
    """Find or create the SOUR record for this citation, keyed by its title.

    Provenance has to be right: people read off a parish register must not be
    cited to the FamilySearch tree just because that is the default. A proposal
    can therefore carry its own `source`, and each distinct title becomes one
    shared SOUR record rather than one per person.
    """
    title = spec["title"].strip()
    if title in made:
        return made[title]
    for rec in ged.of_type("SOUR"):
        if (ged.value(rec.xref, "TITL") or "").strip() == title:
            made[title] = rec.xref
            return rec.xref
    xref = splicer.reserve_xref("S")
    splicer.append_record(
        render_source(
            xref, title, url=spec.get("url"), page=spec.get("page"), text=spec.get("text")
        ),
        why=f"citation @{xref}@ {title}",
    )
    made[title] = xref
    return xref


def _citation_specs(block: dict, shared_only: bool = False) -> list[dict]:
    """A person block's FamilySearch citations, in the shape `_source_record` takes.

    `tools.research` writes these from what FamilySearch cites for the person --
    the parish register the baptism was read off, with its ARK. Importing them
    is the difference between an ancestor who arrives with «FamilySearch Family
    Tree» hung on him and one who arrives with the 1786 baptism that names him.

    Anything without a usable title is dropped rather than imported under a made
    up name: a SOUR record keyed by an empty title would collide with the next
    one and quietly merge two different documents.
    """
    out: list[dict] = []
    for cite in block.get("citations") or ():
        if not isinstance(cite, dict):
            continue
        if shared_only and not cite.get("shared_with_target"):
            continue
        title = str(cite.get("title") or cite.get("collection") or "").strip()
        if not title:
            continue
        out.append(
            {
                k: v
                for k, v in {
                    "title": title,
                    "url": cite.get("url"),
                    "text": cite.get("text"),
                }.items()
                if v
            }
        )
    return out


def _link_citations(entry: dict) -> list[dict]:
    """The documents that name the child and a proposed parent alike.

    These belong on the FAM record, not only on the people: a register entry
    naming both of them is evidence about the *link*, which is the thing the
    family record asserts and the thing the proposal is asking to accept.
    """
    return [
        spec
        for block in entry.get("parents") or ()
        for spec in _citation_specs(block, shared_only=True)
    ]


def apply_parents(splicer: Splicer, ged: GedcomFile, entries: list[dict]) -> tuple[int, list[str]]:
    """Import parents (and optionally the branch above) for accepted proposals."""
    people = load_people(ged)
    by_pid = {p.fsftid: p for p in people.values() if p.fsftid}
    places = PlaceBook.from_gedcom(ged)
    now = datetime.now()
    today = now.strftime("%d %b %Y").upper()
    now_time = now.strftime("%H:%M:%S")
    notes: list[str] = []

    live = None
    if PEDIGREE.exists():
        live = LiveTree.from_json(json.loads(PEDIGREE.read_text(encoding="utf-8")))

    source_xref: str | None = None
    sources_made: dict[str, str] = {}
    # PID -> xref, for people created during this run.
    created: dict[str, str] = {}
    added_records = 0

    def ensure_person(block: dict, fams: list[str]) -> str | None:
        """Create an INDI for this proposal block, or reuse an existing record."""
        nonlocal added_records
        pid = block.get("fsftid")
        if pid and pid in by_pid:
            existing = by_pid[pid]
            notes.append(
                f"reusing @{existing.xref}@ for {block.get('given','?')} "
                f"{block.get('surname','?')} (already in the tree as {pid})"
            )
            return existing.xref
        if pid and pid in created:
            return created[pid]
        # The tree source says where the person came from; the citations say
        # what the claim rests on. Both hang on the record, in that order.
        # dict.fromkeys and not set(): one document cited twice is one SOUR
        # pointer, but the order the proposal listed them in is the order the
        # reviewer read them in.
        cited = list(dict.fromkeys(
            _source_record(splicer, ged, spec, sources_made)
            for spec in _citation_specs(block)
        ))
        xref = splicer.reserve_xref("I")
        splicer.append_record(
            render_individual(
                xref,
                given=block.get("given", ""),
                surname=block.get("surname", ""),
                sex=block.get("sex"),
                birth_date=block.get("birth_date"),
                birth_place=block.get("birth_place"),
                death_date=block.get("death_date"),
                death_place=block.get("death_place"),
                fsftid=pid,
                source_xrefs=([source_xref] if source_xref else []) + cited,
                object_files=block.get("documents") or [],
                fams=fams,
                places=places,
                change_date=today,
                change_time=now_time,
            ),
            why=f"new person @{xref}@ {block.get('given','')} {block.get('surname','')}",
        )
        added_records += 1
        if pid:
            created[pid] = xref
        return xref

    for entry in accepted(entries):
        if entry.get("kind") != "parents":
            notes.append(f"skipped a '{entry.get('kind')}' proposal: not importable automatically")
            continue
        target = str(entry["target"]).strip("@")
        child = people.get(target)
        if child is None:
            notes.append(f"skipped {target}: no such record")
            continue
        if child.famc:
            notes.append(
                f"SKIPPED @{target}@ {child.label()}: already has parents "
                f"(@{child.famc}@) — resolve by hand"
            )
            continue
        source_xref = _source_record(
            splicer, ged, entry.get("source") or FS_TREE_SOURCE, sources_made
        )

        # A document that names the child and a parent together is evidence for
        # the family, so it is made before the FAM record and cited on it. The
        # same title reaching this twice -- both parents on one baptism -- is one
        # SOUR record, because `_source_record` keys them by title.
        # Deduped: one baptism naming the child, the father and the mother is
        # one document, and it reaches this list once per parent that cites it.
        link_xrefs = list(dict.fromkeys(
            _source_record(splicer, ged, spec, sources_made)
            for spec in _link_citations(entry)
        ))
        link_xrefs = [x for x in link_xrefs if x != source_xref]

        # The family the child belongs to, created now so parents can point at it.
        fam_xref = splicer.reserve_xref("F")
        parent_xrefs: dict[str, str | None] = {"M": None, "F": None}
        for block in entry.get("parents") or ():
            xref = ensure_person(block, fams=[fam_xref])
            sex = block.get("sex")
            if sex in ("M", "F") and parent_xrefs[sex] is None:
                parent_xrefs[sex] = xref
            elif xref:
                notes.append(
                    f"@{target}@: parent {block.get('given','?')} has sex "
                    f"{sex!r}; placed as {'HUSB' if sex != 'F' else 'WIFE'}"
                )
                parent_xrefs["M" if sex != "F" else "F"] = (
                    parent_xrefs["M" if sex != "F" else "F"] or xref
                )

        splicer.append_record(
            render_family(
                fam_xref,
                husband=parent_xrefs["M"],
                wife=parent_xrefs["F"],
                children=[target],
                source_xrefs=[source_xref] + link_xrefs,
                places=places,
                change_date=today,
                change_time=now_time,
            ),
            why=f"new family @{fam_xref}@ for @{target}@ {child.label()}",
        )
        added_records += 1
        splicer.insert_into(
            target, [f"1 FAMC @{fam_xref}@"], why=f"link @{target}@ to @{fam_xref}@"
        )

        # The branch above, only when explicitly accepted and resolvable.
        if entry.get("accept_ancestors") is True:
            if live is None:
                notes.append(
                    f"@{target}@: accept_ancestors is true but {PEDIGREE.name} is "
                    "missing; run tools.fs.fetch first. Parents imported only."
                )
                continue
            added_records += _import_branch(
                splicer,
                live,
                entry,
                by_pid,
                created,
                places,
                source_xref,
                today,
                now_time,
                notes,
            )

    if places.unknown:
        notes.append(
            f"{len(places.unknown)} lloc(s) que l'arbre encara no coneix: s'han "
            "escrit amb la grafia original i sense coordenades. Convé revisar-los "
            "un cop a Ancestris (Eines > Llocs) — "
            + "; ".join(sorted(places.unknown))
        )
    return added_records, notes


def _import_branch(
    splicer: Splicer,
    live: LiveTree,
    entry: dict,
    by_pid: dict,
    created: dict[str, str],
    places: PlaceBook,
    source_xref: str,
    today: str,
    now_time: str,
    notes: list[str],
) -> int:
    """Walk up from the accepted parents, creating people and linking families."""
    from .research import person_block

    added = 0
    frontier = [b["fsftid"] for b in entry.get("parents") or () if b.get("fsftid")]
    while frontier:
        nxt: list[str] = []
        for pid in frontier:
            child_xref = created.get(pid) or (by_pid[pid].xref if pid in by_pid else None)
            parents = live.parents(pid)
            if not parents or child_xref is None:
                continue
            # Skip if this person already has parents recorded in the tree.
            fam_xref = splicer.reserve_xref("F")
            slots: dict[str, str | None] = {"M": None, "F": None}
            for parent in parents:
                ppid = parent.xref
                if ppid in by_pid:
                    slots[parent.sex or "M"] = by_pid[ppid].xref
                    continue
                if ppid in created:
                    slots[parent.sex or "M"] = created[ppid]
                    continue
                xref = splicer.reserve_xref("I")
                splicer.append_record(
                    render_individual(
                        xref,
                        given=parent.given,
                        surname=parent.surname,
                        sex=parent.sex,
                        birth_date=parent.birth_date,
                        birth_place=parent.birth_place,
                        death_date=parent.death_date,
                        death_place=parent.death_place,
                        fsftid=ppid,
                        source_xrefs=[source_xref],
                        fams=[fam_xref],
                        places=places,
                        change_date=today,
                        change_time=now_time,
                    ),
                    why=f"ancestor @{xref}@ {parent.given} {parent.surname}",
                )
                created[ppid] = xref
                slots[parent.sex or "M"] = xref
                added += 1
                nxt.append(ppid)
            splicer.append_record(
                render_family(
                    fam_xref,
                    husband=slots["M"],
                    wife=slots["F"],
                    children=[child_xref],
                    source_xrefs=[source_xref],
                    places=places,
                    change_date=today,
                    change_time=now_time,
                ),
                why=f"ancestor family @{fam_xref}@",
            )
            added += 1
            splicer.insert_into(
                child_xref, [f"1 FAMC @{fam_xref}@"], why=f"link @{child_xref}@ upward"
            )
        frontier = nxt
    return added


def apply_children(splicer: Splicer, ged: GedcomFile, entries: list[dict]) -> tuple[int, list[str]]:
    """Add documented children to a family that is already in the tree.

    The other handlers walk upwards, because that is how an ancestor tree grows.
    But a register read for one reason often names people for another: a burial
    book gives the children of a couple who had none recorded, and those children
    are evidence, not decoration -- they are what shows which surname the couple's
    own offspring carried. `target` is the existing FAM; each child becomes an
    INDI with FAMC pointing at it, plus one CHIL line in the family.
    """
    places = PlaceBook.from_gedcom(ged)
    now = datetime.now()
    today = now.strftime("%d %b %Y").upper()
    now_time = now.strftime("%H:%M:%S")
    notes: list[str] = []
    sources_made: dict[str, str] = {}
    added = 0

    for entry in accepted(entries):
        if entry.get("kind") != "children":
            notes.append(f"skipped a '{entry.get('kind')}' proposal: wrong handler")
            continue
        fam = str(entry["target"]).strip("@")
        record = ged.by_xref.get(f"@{fam}@") or ged.by_xref.get(fam)
        if record is None:
            notes.append(f"skipped @{fam}@: no such record")
            continue
        source_xref = _source_record(
            splicer, ged, entry.get("source") or FS_TREE_SOURCE, sources_made
        )
        for block in entry.get("children") or ():
            xref = splicer.reserve_xref("I")
            splicer.append_record(
                render_individual(
                    xref,
                    given=block.get("given", ""),
                    surname=block.get("surname", ""),
                    sex=block.get("sex"),
                    birth_date=block.get("birth_date"),
                    birth_place=block.get("birth_place"),
                    death_date=block.get("death_date"),
                    death_place=block.get("death_place"),
                    fsftid=block.get("fsftid"),
                    source_xrefs=[source_xref] if source_xref else [],
                    object_files=block.get("documents") or [],
                    famc=fam,
                    places=places,
                    change_date=today,
                    change_time=now_time,
                ),
                why=f"new child @{xref}@ {block.get('given','')} {block.get('surname','')}",
            )
            splicer.insert_into(
                fam, [f"1 CHIL @{xref}@"], why=f"link @{xref}@ into @{fam}@"
            )
            added += 1

    if places.unknown:
        notes.append(
            f"{len(places.unknown)} lloc(s) que l'arbre encara no coneix: s'han "
            "escrit amb la grafia original i sense coordenades. Convé revisar-los "
            "un cop a Ancestris (Eines > Llocs) — "
            + "; ".join(sorted(places.unknown))
        )
    return added, notes


HANDLERS = {
    "fsftid": apply_fsftid,
    "parents": apply_parents,
    "children": apply_children,
}


def detect_kind(entries: list[dict]) -> str:
    if not entries:
        raise SystemExit("the review file is empty")
    if "fsftid" in entries[0] and "kind" not in entries[0]:
        return "fsftid"
    kinds = {e.get("kind") for e in entries}
    if "parents" in kinds:
        return "parents"
    if kinds == {"children"}:
        return "children"
    raise SystemExit(
        f"cannot tell what kind of review file this is (kinds seen: {kinds or 'none'})"
    )


def show_diff(before: list[str], after: list[str], name: str, context: int = 2) -> int:
    diff = list(
        unified_diff(before, after, fromfile=f"a/{name}", tofile=f"b/{name}", n=context, lineterm="")
    )
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    for line in diff:
        print(line)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_file", help="YAML file of reviewed proposals")
    parser.add_argument("--gedcom", default=None, help="GEDCOM to modify")
    parser.add_argument("--write", action="store_true", help="actually modify the file")
    parser.add_argument("--quiet", action="store_true", help="skip printing the diff")
    args = parser.parse_args()

    path = Path(args.review_file)
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(entries, list):
        raise SystemExit(f"{path}: expected a YAML list of proposals")
    validate(entries)

    pending = sum(1 for e in entries if e.get("accept") is None)
    rejected = sum(1 for e in entries if e.get("accept") is False)
    ok = accepted(entries)
    print(
        f"{path.name}: {len(entries)} proposals — {len(ok)} accepted, "
        f"{rejected} rejected, {pending} still undecided"
    )
    if not ok:
        print("nothing accepted; nothing to do")
        return 0

    ged = GedcomFile(args.gedcom or tree_path())
    splicer = Splicer(ged)
    applied, notes = HANDLERS[detect_kind(entries)](splicer, ged, entries)
    for note in notes:
        print(f"  {note}")
    if not applied:
        print("nothing to apply")
        return 0

    # Both sides are compared with the Ancestris d'Aboville duplicates already
    # removed, so the additive guard below still means what it says. Dropping
    # them is not this proposal's doing and must not read as one of its
    # deletions -- it is reported on its own line instead.
    before, dropped = dedupe_sosa(ged.raw)
    after, _ = dedupe_sosa(splicer.apply())
    if dropped:
        print(f"  {len(dropped)} duplicate {SOSA_TAG} line(s) dropped on write")

    if not args.quiet:
        removed = show_diff(before, after, ged.path.name)
        if removed:
            print(f"\nREFUSING: the diff removes {removed} lines; this must be additive")
            return 1

    print(
        f"\n{applied} change(s) to {ged.path.name}: "
        f"+{len(after) - len(before)} lines, no deletions"
    )
    if not args.write:
        print("dry run — pass --write to apply")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ged.path.with_name(f"{ged.path.stem}_{stamp}{ged.path.suffix}")
    shutil.copy2(ged.path, backup)
    ged.write(ged.path, after)
    print(f"wrote {ged.path.name}; previous version kept as {backup.name}")

    # Prove the result still parses and gained exactly what we intended.
    reread = GedcomFile(ged.path)
    print(
        f"re-read: {len(reread.raw)} lines "
        f"(was {len(ged.raw)}, +{len(reread.raw) - len(ged.raw)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

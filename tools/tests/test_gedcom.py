"""Acceptance tests for the GEDCOM module.

Two kinds of test live here, and the split is deliberate:

  * **Invariants, run against YOUR tree** (whatever config.yaml points at). The
    first is the one that matters: if reading and rewriting your file is not
    byte-identical, nothing downstream can be trusted. These assert nothing about
    who is in the file, so they keep passing as the tree grows.

  * **Values, run against `exemple.ged`**. Anything that asserts a name, a count
    or a coordinate goes here. Asserting values against a live tree produces a
    test that has to be edited after every import -- and a test that gets edited
    routinely is a test nobody reads.

    python3 -m tools.tests.test_gedcom
"""

from __future__ import annotations

import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from tools import config
from tools.gedcom.lines import SOSA_TAG, GedcomFile, dedupe_sosa
from tools.gedcom.splice import Splicer

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "exemple.ged"

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_byte_identical_roundtrip(path: Path) -> None:
    """THE test. Everything else assumes this one passes."""
    print(f"\nround-trip {path.name}")
    original = path.read_bytes()
    ged = GedcomFile(path)
    rendered = ged.render().encode("utf-8")
    check(rendered == original, "rewrite is byte-identical",
          f"{len(rendered)} vs {len(original)} bytes")
    check(ged.has_bom, "BOM detected and preserved")
    check(ged.newline == "\n", "LF line endings detected")

    # Trailing whitespace must survive. Ancestris really writes SURN values with
    # a trailing space, and a re-serialising GEDCOM library would eat them --
    # which would make the next write look like a change to the whole file.
    with_trailing = [r for r in ged.raw if r != r.rstrip()]
    if with_trailing:
        rendered_text = ged.render()
        check(
            all(f"{r}\n" in rendered_text for r in with_trailing),
            f"{len(with_trailing)} trailing-whitespace line(s) preserved",
        )


def test_parsing() -> None:
    print("\nparsing the example tree")
    ged = GedcomFile(EXAMPLE)

    # Counts are checked against the file itself rather than hard-coded, so this
    # keeps working if the example ever grows a generation.
    raw = EXAMPLE.read_text(encoding="utf-8-sig").splitlines()
    for tag in ("INDI", "FAM", "SOUR", "NOTE"):
        # A record line is `0 @xref@ TAG` and may carry inline text after the
        # tag, as NOTE records do, so match the tag position rather than the end.
        expected = sum(
            1 for line in raw
            if line.startswith("0 @") and line.split(" ")[2:3] == [tag]
        )
        got = len(ged.of_type(tag))
        check(got == expected, f"{got} {tag} records, matching a raw scan", str(expected))

    # A known record, verified verbatim against the file.
    check(ged.value("I00001", "NAME") == "Aina /FIGUEROLA SEGARRA/", "I00001 NAME parsed")
    check(ged.value("I00001", "SEX") == "F", "I00001 SEX parsed")
    check(ged.value("I00001", "FAMC") == "@F00001@", "I00001 FAMC parsed")
    famc = ged.sub("I00001", "FAMC")[0]
    check(famc.pointer == "F00001", "pointer extracted from FAMC")

    # Nested lookup: BIRT > DATE, and the deeper PLAC under it.
    birt = ged.sub("I00001", "BIRT")[0]
    date = ged.nested(birt, "DATE", "I00001")
    plac = ged.nested(birt, "PLAC", "I00001")
    check(date is not None and date.value == "12 MAR 2001", "BIRT>DATE nested lookup")
    check(
        plac is not None and plac.value == ", Girona, , Girona, Catalunya, Espanya",
        "BIRT>PLAC six-level format intact",
    )

    # The custom Ancestris tag must be visible, not swallowed.
    check(ged.value("I00001", "_SOSADABOVILLE") == "1 G1", "_SOSADABOVILLE readable")

    # Ancestris regenerates this tag on save, and it writes DUPLICATES: the same
    # value reappears after every save and is never de-duplicated. We read the tag
    # and never write it, so they are harmless -- but a parser that silently kept
    # only the last one would hide a real property of the file.
    sosa = [r for r in ged.of_type("INDI") if ged.sub(r.xref, "_SOSADABOVILLE")]
    total = sum(len(ged.sub(r.xref, "_SOSADABOVILLE")) for r in sosa)
    check(len(sosa) >= 1, "the Sosa-numbered individuals are found", str(len(sosa)))
    check(
        total > len(sosa),
        "more tag lines than individuals: the known duplicates are visible",
        f"{total} lines over {len(sosa)} people",
    )

    # A trailing-space surname is exposed stripped but stored raw.
    raw_surn = [r for r in ged.raw if r == "2 SURN MASCARELL NOGUÉS "]
    check(len(raw_surn) == 1, "raw trailing-space SURN retained")

    for prefix in ("I", "F", "S"):
        top = ged.max_xref(prefix)
        check(
            ged.next_xref(prefix) == f"{prefix}{top + 1:05d}",
            f"next {prefix} xref follows the highest ({top})",
            ged.next_xref(prefix),
        )
        check(
            f"{prefix}{top:05d}" in ged.by_xref,
            f"highest {prefix} xref exists and is zero-padded to five digits",
        )


def test_fsftid_shape(path: Path) -> None:
    """Whatever carries a _FSFTID must carry something shaped like a PID.

    Deliberately not a count. How many of your people are linked to FamilySearch
    is a fact about your research, and it changes every time you import; that it
    is never the same id twice is a fact about the file, and it must always hold.
    """
    print(f"\nFamilySearch ids in {path.name}")
    ged = GedcomFile(path)
    indis = ged.of_type("INDI")
    ids = [ged.value(r.xref, "_FSFTID") for r in indis]
    present = [i for i in ids if i]
    check(bool(present), f"{len(present)} of {len(indis)} individuals carry a _FSFTID")
    check(len(set(present)) == len(present), "no _FSFTID is used twice",
          f"{len(present) - len(set(present))} repeated")
    check(all(len(i) >= 7 and "-" in i for i in present), "they look like FS PIDs")


def test_splice_noop() -> None:
    print("\nsplice: no-op")
    ged = GedcomFile(EXAMPLE)
    sp = Splicer(ged)
    check(sp.pending == 0, "nothing pending")
    check(sp.apply() == ged.raw, "empty splice returns the original lines")


def test_splice_append_and_insert() -> None:
    print("\nsplice: append + insert")
    ged = GedcomFile(EXAMPLE)
    sp = Splicer(ged)

    top = ged.max_xref("I")
    new_id = sp.reserve_xref("I")
    check(new_id == f"I{top + 1:05d}", f"reserved the next free xref after {top}", new_id)
    check(
        sp.reserve_xref("I") == f"I{top + 2:05d}",
        "a second reservation does not collide with the first",
    )

    new_xref = f"@{new_id}@"
    sp.append_record(
        [f"0 {new_xref} INDI", "1 NAME Test /PROVA/", "2 GIVN Test", "2 SURN PROVA"],
        why="test individual",
    )
    # A sentinel value, so the assertions hold no matter what tags the file may
    # have acquired from earlier runs of tools/apply.py.
    sentinel = "1 _TESTTAG SENTINEL-0001"
    sp.insert_into("I00001", [sentinel], why="sentinel insert")
    result = sp.apply()

    check(len(result) == len(ged.raw) + 5, "5 lines added", f"{len(result) - len(ged.raw)}")

    # The appended record must sit immediately before 0 TRLR.
    trlr = result.index("0 TRLR")
    check(result[trlr - 4] == f"0 {new_xref} INDI", "new record precedes TRLR")
    check(result[trlr - 1] == "2 SURN PROVA", "new record ends just before TRLR")

    # The inserted line must sit directly before I00001's 1 CHAN, and inside
    # I00001's own line range rather than anywhere else in the file.
    i = result.index(sentinel)
    check(result[i + 1] == "1 CHAN", "insert lands before 1 CHAN")
    rec = ged.by_xref["I00001"]
    check(rec.start < i <= rec.end, "insert lands inside I00001's record", f"{i} vs {rec}")
    check(result[i - 1].startswith("1 "), "insert follows another level-1 tag", result[i - 1])

    # The property that actually matters: a diff of original -> result contains
    # insertions only. No line is ever deleted, reordered or rewritten, so
    # `git diff` can only ever show additions.
    ops = SequenceMatcher(a=ged.raw, b=result, autojunk=False).get_opcodes()
    destructive = [o for o in ops if o[0] in ("delete", "replace")]
    check(not destructive, "diff contains insertions only", f"{destructive[:2]}")
    inserted = [
        line for tag, _, _, j1, j2 in ops if tag == "insert" for line in result[j1:j2]
    ]
    check(len(inserted) == 5, "exactly the 5 intended lines inserted", str(len(inserted)))
    check(sentinel in inserted, "the spliced tag is among them")

    # And a written file differs from the original only by additions.
    with tempfile.TemporaryDirectory() as tmp:
        out = sp.write(Path(tmp) / "out.ged")
        written = out.read_bytes().decode("utf-8")
        check(written.startswith("﻿"), "written file keeps the BOM")
        check(written.endswith("0 TRLR\n"), "written file ends with 0 TRLR + newline")


def test_additive_only(path: Path) -> None:
    """The same additive guarantee, checked against the real tree.

    Splicing into a file with hundreds of records has failure modes an
    eighteen-person example cannot show: a record whose line range is computed
    wrong, an insertion point that lands in the neighbouring record. So this runs
    against whatever tree config.yaml names, and asserts only the property.
    """
    print(f"\nsplice is additive on {path.name}")
    ged = GedcomFile(path)
    first = next(iter(ged.of_type("INDI")), None)
    if first is None:
        check(False, "the tree has at least one individual")
        return
    sp = Splicer(ged)
    sp.insert_into(first.xref, ["1 _TESTTAG SENTINEL-0002"], why="additive check")
    result = sp.apply()
    ops = SequenceMatcher(a=ged.raw, b=result, autojunk=False).get_opcodes()
    destructive = [o for o in ops if o[0] in ("delete", "replace")]
    check(not destructive, "no line deleted, reordered or rewritten", f"{destructive[:2]}")
    check(len(result) == len(ged.raw) + 1, "exactly one line added")
    check(GedcomFile(path).raw == ged.raw, "the file on disk is untouched")


def test_place_lookup_never_relocates() -> None:
    """A province in second place must not be mistaken for the town.

    A regression test with a scar behind it. `PlaceBook.lookup` is the method
    whose whole purpose is to refuse a broad fallback, and it once resolved
    "Terrades, Girona, Catalonia, Spain" to the CITY of Girona and handed over the
    city's coordinates -- forty kilometres from Terrades. Every province the tree
    touched was listed as broad except Girona, and Girona is the only one that is
    also a town, so the hole stayed invisible everywhere else.
    """
    print("\nrender.py: un lloc nou no relocalitza ningú")
    from tools.render import PlaceBook

    pb = PlaceBook.from_gedcom(GedcomFile(EXAMPLE))

    # Towns the file does not know must come back WITHOUT coordinates, and be
    # reported, rather than borrowing the province capital's. Deliberately
    # invented names, so importing real places can never make this pass by luck.
    for unknown in ("Prova de Dalt", "Sant Just de Prova"):
        place = f"{unknown}, Girona, Catalunya, Espanya"
        out = pb.lookup(place)
        check(
            not any("LATI" in line for line in out),
            f"«{unknown}» no hereta coordenades de la ciutat de Girona",
            "; ".join(out),
        )
        check(unknown in out[0], f"«{unknown}» conserva el seu nom", out[0])
        check(place in pb.unknown, f"«{unknown}» queda reportat com a desconegut")

    # But a province name LEADING is a real place: somebody was born in the city.
    city = pb.lookup("Girona, Girona, Catalunya, Espanya")
    check(any("LATI" in line for line in city), "la ciutat de Girona sí que resol",
          "; ".join(city))

    # And a town the file does know must still reach its own coordinates.
    known = pb.lookup("Lladó, Girona, Catalunya, Espanya")
    check(any("N42.24769" in line for line in known), "Lladó continua resolent",
          "; ".join(known))


def test_correct_delete_guards() -> None:
    """`delete` is the only op that loses lines, so test what it REFUSES.

    The dangerous case is not deleting the wrong line -- the verbatim-block rule
    already catches that. It is deleting a parent and leaving its children, which
    produces a file that still parses while meaning something else entirely.
    """
    print("\ncorrect.py: els guards del delete")
    from tools import correct

    # A fixture, not a real file. The first version of this test read the
    # coordinates straight out of a real record -- and then the very correction it
    # was written for deleted them, so the test started erroring instead of
    # failing. A test that breaks when the data it asserts about is legitimately
    # changed is testing the data, not the code.
    fixture = "\n".join([
        "0 HEAD",
        "1 CHAR UTF-8",
        "0 @I00001@ INDI",
        "1 NAME Prova /FIXTURA/",
        "1 BIRT",
        "2 DATE 5 AUG 1891",
        "2 PLAC , Santa Eulàlia, , Girona, Catalunya, Espanya",
        "3 MAP",
        "4 LATI N42.17366",
        "4 LONG E2.96474",
        "1 DEAT",
        "2 DATE 3 MAY 1958",
        "2 PLAC , Fortià, , Girona, Catalunya, Espanya",
        "3 MAP",                       # a second MAP: makes "3 MAP" ambiguous
        "4 LATI N42.2432",
        "4 LONG E3.03881",
        "1 CHAN",
        "2 DATE 22 SEP 2025",
        "3 TIME 21:36:54",
        "0 TRLR",
        "",
    ])
    stamp = ("28 JUL 2026", "12:00:00")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixtura.ged"
        path.write_text(fixture, encoding="utf-8")
        ged = GedcomFile(path)
        _delete_guard_assertions(correct, ged, stamp)


def _delete_guard_assertions(correct, ged, stamp) -> None:
    def run(edits, target="I00001"):
        entry = [{"target": target, "why": "prova", "edits": edits, "accept": True}]
        return correct.plan(ged, entry, *stamp)

    def refuses(label, edits, expect: str, target="I00001"):
        try:
            run(edits, target)
        except correct.Refused as exc:
            check(expect in str(exc), f"refusa: {label}", f"deia «{exc}»")
        else:
            check(False, f"refusa: {label}", "no ha refusat")

    # The shape this was built for: LATI/LONG hang off MAP, so all three go together.
    good = ["3 MAP", "4 LATI N42.17366", "4 LONG E2.96474"]
    replacements, insertions, deletions, touched, _ = run([{"delete": good}])
    check(len(deletions) == 3, "esborra les tres línies del bloc", str(len(deletions)))
    after = correct.render(ged, replacements, insertions, deletions)
    check(len(after) == len(ged.raw) - 3, "el fitxer queda 3 línies més curt",
          f"{len(after) - len(ged.raw)}")
    check("4 LATI N42.17366" not in after, "la latitud inventada ja no hi és")
    check(after.count("2 PLAC , Santa Eulàlia, , Girona, Catalunya, Espanya") == 1,
          "el lloc es queda")

    # Every line still parses, and no line is left deeper than its parent.
    levels = [int(r.split(" ", 1)[0]) for r in after if r and r[0].isdigit()]
    jumps = [(a, b) for a, b in zip(levels, levels[1:]) if b > a + 1]
    check(not jumps, "cap salt de nivell al fitxer resultant", str(jumps[:3]))

    # THE guard: take the parent, leave the children.
    #
    # Note which guard fires first. `3 MAP` on its own is what you would reach for
    # here, but it appears TWICE inside the record -- once under BIRT and once
    # under DEAT -- so the ambiguity rule stops it before the orphan rule gets a
    # look in. Two guards, and the blunter one is in front. So the orphan guard
    # has to be tested with lines that are unique inside the record.
    place = "2 PLAC , Santa Eulàlia, , Girona, Catalunya, Espanya"
    refuses("esborrar el PLAC i deixar-hi el MAP penjant",
            [{"delete": [place]}], "deixaria orfe")
    refuses("esborrar MAP i LATI però no LONG",
            [{"delete": ["3 MAP", "4 LATI N42.17366"]}], "deixaria orfe")
    refuses("un 3 MAP a seques, que dins d'aquest registre surt dues vegades",
            [{"delete": ["3 MAP"]}], "hi surt 2 vegades")

    # A block that starts deeper than it ends is not a subtree either.
    refuses("un bloc que comença més profund que acaba",
            [{"delete": ["4 LONG E2.96474", "1 DEAT"]}], "ha de començar pel nivell més alt")

    # Verbatim or nothing: a plausible-looking near-miss must not be guessed at.
    refuses("una línia gairebé bé",
            [{"delete": ["4 LATI N42.17366 "]}], "no s'hi troba el bloc")
    refuses("línies bones però no seguides",
            [{"delete": ["3 MAP", "4 LONG E2.96474"]}], "no s'hi troba el bloc")

    # The CHAN stamp is what records when we touched a record; deleting it would
    # make the file lie about its own history.
    refuses("esborrar el CHAN", [{"delete": ["1 CHAN"]}], "CHAN")

    # Whole records are Ancestris's job, not this tool's.
    refuses("esborrar un registre sencer",
            [{"delete": ["0 @I00001@ INDI"]}], "nivell 0")

    refuses("un delete buit", [{"delete": []}], "buit")

    # And the same line cannot be deleted and corrected at once.
    refuses("esborrar i corregir la mateixa línia",
            [{"find": "4 LONG E2.96474", "replace": "4 LONG E2.96474"},
             {"delete": good}],
            "decidiu-vos")

    # The fixture on disk must be untouched by all of the above: plan() decides,
    # it never writes.
    check(GedcomFile(ged.path).raw == ged.raw, "el fitxer del disc no s'ha tocat")


def test_dedupe_sosa() -> None:
    """The de-duplication that `write` does on every save.

    Ancestris appends a fresh `_SOSADABOVILLE` line on each save instead of
    replacing the one already there, so a long-lived tree accumulates several
    lines where one belongs. `write` drops them, and this is where the rule is
    pinned down: KEEP THE LAST, because the stale line comes first and the
    current calculation is appended behind it.
    """
    print("\ndedupe _SOSADABOVILLE")
    raw = [
        "0 @I1@ INDI",
        "1 NAME A /B/",
        "1 _SOSADABOVILLE 54-2 G5",   # stale: this is the one that must go
        "1 _SOSADABOVILLE 54-1 G5",
        "1 _SOSADABOVILLE 54-1 G5",
        "1 SEX M",
        "0 @I2@ INDI",                # a single line is left alone
        "1 _SOSADABOVILLE 4 G3",
        "0 TRLR",
    ]
    cleaned, dropped = dedupe_sosa(raw)
    check(len(dropped) == 2, "the two extra lines are dropped", str(len(dropped)))
    check(
        [ln for ln in cleaned if SOSA_TAG in ln]
        == ["1 _SOSADABOVILLE 54-1 G5", "1 _SOSADABOVILLE 4 G3"],
        "the LAST line of each record survives",
    )
    check(len(cleaned) == len(raw) - 2, "nothing else is touched", str(len(cleaned)))
    check(dedupe_sosa(cleaned) == (cleaned, []), "idempotent: a second pass is a no-op")

    # A file with no duplicates must come back untouched, or every save would
    # rewrite the file for nothing.
    clean = ["0 @I1@ INDI", "1 _SOSADABOVILLE 4 G3", "0 TRLR"]
    check(dedupe_sosa(clean) == (clean, []), "a clean file is returned unchanged")

    # The tag only counts at level 1 inside a record, and record boundaries are
    # what separate one person's lines from the next.
    two = ["0 @I1@ INDI", "1 _SOSADABOVILLE 4 G3", "0 @I2@ INDI", "1 _SOSADABOVILLE 4 G3", "0 TRLR"]
    check(dedupe_sosa(two) == (two, []), "one line each in two records is not a duplicate")

    # And it survives the round trip against a real file: `exemple.ged` already
    # carries a genuine Ancestris duplicate (I00012), so writing it out leaves
    # one line per person instead of accumulating a second copy.
    ged = GedcomFile(EXAMPLE)
    with tempfile.TemporaryDirectory() as tmp:
        out = ged.write(Path(tmp) / "out.ged")
        reread = GedcomFile(out)
        dupes = [
            r.xref
            for r in reread.of_type("INDI")
            if len(reread.sub(r.xref, SOSA_TAG)) > 1
        ]
        check(not dupes, "a written file has no duplicate _SOSADABOVILLE lines", str(dupes[:3]))


def main() -> int:
    if not EXAMPLE.exists():
        print(f"missing {EXAMPLE}: the value tests need it")
        return 2

    # Values, always against the example.
    test_byte_identical_roundtrip(EXAMPLE)
    test_parsing()
    test_fsftid_shape(EXAMPLE)
    test_splice_noop()
    test_splice_append_and_insert()
    test_place_lookup_never_relocates()
    test_correct_delete_guards()
    test_dedupe_sosa()

    # Invariants, against the real tree: the ones that protect your data.
    try:
        yours = config.tree_path()
    except SystemExit as exc:
        print(f"\n(cap arbre propi comprovat: {exc})")
        yours = EXAMPLE
    if yours != EXAMPLE:
        test_byte_identical_roundtrip(yours)
        test_fsftid_shape(yours)
        test_additive_only(yours)
    else:
        print("\n(config.yaml encara apunta a exemple.ged. Quan hi posis el teu arbre,")
        print(" aquestes proves el comprovaran a ell també, que és el que importa.)")

    # An old FamilySearch export, if config.yaml names one.
    dump = config.fs_dump_path()
    if dump:
        test_byte_identical_roundtrip(dump)
        test_fsftid_shape(dump)

    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

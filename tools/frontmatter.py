"""Our own frontmatter vocabulary, and the checks over it.

The keys are Catalan and they are ours. No plugin defines them, nothing outside
this repository has to understand them, and **no note carries a `cr_id`** -- the
one key that would let a third-party writer edit these files (see
`tools.obsidian`, which exports around the same plugin without arming it).

The key that pays for the whole exercise is `classe`. `original` versus `index`
is a distinction that matters and is easy to lose track of once there are
hundreds of notes -- until it is a key, it lives only as a sentence inside each
`**Font**:` paragraph. As a key it can be asked a question: *give me every fact
resting on an index and nothing else*. That is a research worklist that could
not be obtained at all before.

`arxiu:` is the one key whose valid values are not fixed by the tool: which
archives you use is family-specific, so the list comes from `config.yaml`, at
`frontmatter: arxius:`. Empty, as the template ships, nothing is rejected.

    python -m tools.frontmatter          # what has frontmatter and what it says
    python -m tools.frontmatter --check  # validate (also run by tools.lint)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from . import config
from .config import tree_path

from .config import ROOT
FONTS = ROOT / "Fonts"
PERSONES = ROOT / "Persones"

# What kind of document the note is. Not what it says, and not how much it is
# worth -- that is `classe` below -- but which of the handful of jobs a note in
# `Fonts/` can be doing.
#
# `tramit` is the paperwork an archive makes you file, and the answer it sends
# back: a formal request under a records law, the reply saying what was found and
# what was not. It earns its own value because it is neither of the two it would
# otherwise be filed under. Not a `transcripcio`: nothing historical is being
# transcribed, and the document is one we produced or received this year rather
# than something read out of a book. Not a `recerca` either: a research note
# records what somebody worked out, while this records what was asked for, on
# what date, under which reference, and what came back. Filing one is often the
# only route to a record at all, so the request and its answer are worth keeping
# whether or not they turn anything up -- a "we hold nothing for those years" is
# a result, and the note is what stops it being asked again.
TIPUS = {"transcripcio", "cas", "recerca", "informe", "familia", "persona", "tramit"}

# How the document relates to the event it records. This is the confidence
# hierarchy worth writing down, made answerable.
CLASSE = {
    "original": "la imatge o el document original: mana sobre tot el demés",
    "index": "una fitxa de l'índex, no del manuscrit: prova de segona mà d'una primària",
    "consulta": "algú ho va llegir al llibre i no en tenim imatge: no es pot rellegir",
    "memoria": "memòria d'una persona, oral o escrita",
    "narrativa": "un treball redactat per algú: llibre, treball de recerca, quadre de casa",
}

CONFIANCA = {"alta", "mitjana", "baixa"}

_XREF = re.compile(r"^@I\d{5}@$")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")

# `![[Nota#Secció]]` -- a section embed, which is core Obsidian and is what lets a
# person's note show a case's reasoning without copying it.
_EMBED = re.compile(r"!\[\[([^\]#|]+)#([^\]|]+)\]\]")


def notes() -> list[Path]:
    folders = [FONTS, PERSONES]
    return sorted(
        p
        for folder in folders
        if folder.exists()
        for p in folder.rglob("*.md")
        if ".obsidian" not in p.parts
    )


def read(path: Path) -> dict | None:
    """The YAML frontmatter of a note, or None if it has none.

    Raises on invalid YAML on purpose: an unquoted `@I00103@` or a `:` inside an
    unquoted title is exactly the family of bug that can corrupt a whole batch
    of notes on import, and it must fail loudly rather than be skipped.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    _, _, rest = text.partition("---\n")
    block, sep, _ = rest.partition("\n---")
    if not sep:
        raise ValueError(f"{path}: el frontmatter no es tanca")
    loaded = yaml.safe_load(block)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path}: el frontmatter no és un mapa")
    return loaded


def check(report, tree=None) -> None:
    """Validate every note's frontmatter. `report` is a tools.lint.Report."""
    arxius = config.frontmatter_archives()
    seen_titles: dict[str, str] = {}
    with_frontmatter = 0

    for path in notes():
        relative = str(path.relative_to(ROOT))
        try:
            data = read(path)
        except (ValueError, yaml.YAMLError) as exc:
            report.fail(relative, f"YAML invàlid: {str(exc).splitlines()[0]}")
            continue
        if data is None:
            continue
        with_frontmatter += 1

        if "cr_id" in data:
            report.fail(relative, "porta cr_id: això arma els escriptors del connector")

        tipus = data.get("tipus")
        if tipus not in TIPUS:
            report.fail(relative, f"tipus {tipus!r} no és dels declarats")

        arxiu = data.get("arxiu")
        if arxiu is not None and arxius and arxiu not in arxius:
            report.fail(relative, f"arxiu {arxiu!r} no és dels declarats al config.yaml")

        classe = data.get("classe")
        if tipus == "transcripcio" and classe not in CLASSE:
            report.fail(relative, f"classe {classe!r} no és de les declarades")

        confianca = data.get("confianca")
        if confianca is not None and confianca not in CONFIANCA:
            report.fail(relative, f"confianca {confianca!r} no és de les declarades")

        titol = data.get("titol")
        if tipus == "transcripcio" and not titol:
            report.fail(relative, "sense titol")
        if titol:
            if titol in seen_titles:
                report.fail(relative, f"titol repetit, també a {seen_titles[titol]}")
            seen_titles[titol] = relative

        xrefs = data.get("xrefs") or []
        if not isinstance(xrefs, list):
            report.fail(relative, "xrefs ha de ser una llista")
            xrefs = []
        for xref in xrefs:
            if not isinstance(xref, str) or not _XREF.match(xref):
                report.fail(relative, f"xref {xref!r} mal format (cal «@I00001@»)")
            elif tree is not None and xref.strip("@") not in tree.people:
                report.fail(relative, f"xref {xref} no existeix al GEDCOM")

        # Every image must resolve to exactly one file. Resolution elsewhere is by
        # basename, so a future collision would silently show the wrong scan.
        for image in data.get("imatges") or []:
            candidate = ROOT / image
            if not candidate.is_file():
                report.fail(relative, f"imatge que no existeix: {image}")
                continue
            same_name = [
                p for p in FONTS.rglob(candidate.name) if ".obsidian" not in p.parts
            ]
            if len(same_name) > 1:
                report.fail(
                    relative,
                    f"el nom {candidate.name} és a {len(same_name)} llocs: "
                    "es resol pel nom i mostraria el que no toca",
                )

        captions = data.get("descripcio_imatges") or []
        images = data.get("imatges") or []
        if captions and len(captions) != len(images):
            report.fail(
                relative,
                f"{len(captions)} descripcions per a {len(images)} imatges",
            )

        # Wikilinks must resolve, and unambiguously.
        for key in ("casos", "fonts", "persones"):
            for value in data.get(key) or []:
                for target in _WIKILINK.findall(str(value)):
                    matches = [
                        p
                        for p in ROOT.rglob(f"{Path(target).name}.md")
                        if ".obsidian" not in p.parts and "Charted Roots" not in p.parts
                    ]
                    if not matches:
                        report.fail(relative, f"{key}: [[{target}]] no resol")
                    elif len(matches) > 1:
                        report.fail(relative, f"{key}: [[{target}]] és ambigu")

    check_embeds(report)
    report.note(f"{with_frontmatter} de {len(notes())} fitxes amb frontmatter")


def check_embeds(report) -> None:
    """Every `![[Nota#Secció]]` resolves, section included.

    These carry the weight of the whole arrangement: a person's note *shows* a
    case's reasoning instead of repeating it, and that only works while the target
    section exists under exactly that heading. Rename a heading in a case file and
    the embed silently renders as a broken link -- which is the one failure mode
    that would push somebody to copy the text back in.
    """
    embeds = broken = 0
    for path in notes():
        relative = str(path.relative_to(ROOT))
        for match in _EMBED.finditer(path.read_text(encoding="utf-8")):
            target, section = match.group(1), match.group(2).strip()
            embeds += 1
            hits = [
                p
                for p in ROOT.rglob(f"{Path(target).name}.md")
                if ".obsidian" not in p.parts and "Charted Roots" not in p.parts
            ]
            if not hits:
                report.fail(relative, f"l'embed [[{target}]] no existeix")
                broken += 1
                continue
            if len(hits) > 1:
                report.fail(relative, f"l'embed [[{target}]] és ambigu")
                broken += 1
                continue
            headings = {
                line.lstrip("#").strip()
                for line in hits[0].read_text(encoding="utf-8").split("\n")
                if line.startswith("#")
            }
            if section not in headings:
                report.fail(
                    relative,
                    f"l'embed [[{target}#{section}]]: la secció no hi és",
                )
                broken += 1
    report.note(f"{embeds} embeds de secció, {broken} trencats")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        from .lint import Report
        from .people import Tree

        report = Report()
        check(report, Tree(tree_path()))
        return report.show("problemes de frontmatter")

    by_class: dict[str, list[str]] = {}
    for path in notes():
        data = read(path)
        if not data:
            continue
        key = f"{data.get('arxiu', '—')}/{data.get('classe', '—')}"
        by_class.setdefault(key, []).append(path.name)
    for key in sorted(by_class):
        print(f"{key}  ({len(by_class[key])})")
        for name in sorted(by_class[key]):
            print(f"    {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

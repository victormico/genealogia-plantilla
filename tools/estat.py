"""The tree's live numbers, computed instead of retyped.

A count copied into prose by hand drifts the moment the tree changes, and it
can drift **twice in the same document** without anyone noticing, because
nothing ever compares the two mentions to each other. `tools.lint --xifres`
is the check that catches that; this is what it checks against.

The generation table is the one that needs real work: recompute by walking the
`FAMC` links from the root instead of reading Sosa labels, because Ancestris
labels each person with their lowest Sosa number only, so reading
`_SOSADABOVILLE` undercounts implex. `Tree.ancestors()` walks the links, and by
default skips a `2 PEDI foster` -- a filiation the tree records but a document
does not support -- which is why a generation's filled slots can be fewer than
the `2^(n-1)` that are structurally possible. A tree where the biological line
is gone for good and the family that raised someone is the only ascendency it
will ever have says so in `config.yaml`, under
`estat.filiacions_que_compten`; see `config.counted_filiations()`.

Usage:

    python -m tools.estat            # writes reports/estat.md
    python -m tools.estat --print    # to stdout, writes nothing
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import config
from .config import tree_path
from .people import Tree

from .config import ROOT
FONTS = ROOT / "Fonts"
REPORTS = ROOT / "reports"

# Paths inside the GEDCOM that point at Fonts/. Non-greedy up to an extension,
# because folder names contain spaces and one line can carry two paths -- both
# bugs are documented in Fonts/00 LLEGIU-ME.md, and both were found the hard way.
_FONTS_PATH = re.compile(r"Fonts/.*?\.(?:md|pdf|jpg|jpeg|png|svg|txt|xlsx|docx|ogg|eml|html)")


def _default_root(tree: Tree) -> str | None:
    """`_SOSADABOVILLE 1` — the de cuius Ancestris itself already marks."""
    for person in tree.people.values():
        if person.sosa and person.sosa.split()[0] == "1":
            return person.xref
    return None


class Estat:
    """Every number the prose would otherwise have to retype."""

    def __init__(self, canonical: Path | None = None, root: str | None = None):
        self.tree = Tree(canonical or tree_path())
        self.root = root or config.estat_root() or _default_root(self.tree)
        self.counted = config.counted_filiations()
        self.slots = (
            self.tree.ancestors(self.root, counted=self.counted) if self.root else {}
        )
        self.slots_with_foster = (
            self.tree.ancestors(self.root, birth_only=False) if self.root else {}
        )

    # -- people -----------------------------------------------------------

    @property
    def people(self) -> int:
        return len(self.tree.people)

    @property
    def families(self) -> int:
        return len(self.tree.families)

    @property
    def with_fsftid(self) -> int:
        return len(self.tree.by_fsftid)

    @property
    def without_parents(self) -> int:
        return len(self.tree.leaves())

    @property
    def period(self) -> tuple[int, int]:
        years = [
            y
            for p in self.tree.people.values()
            for y in (p.birth_year, p.death_year)
            if y
        ]
        return (min(years), max(years)) if years else (0, 0)

    # -- generations ------------------------------------------------------

    def generation(self, n: int) -> tuple[int, int]:
        """(slots filled, slots possible) for generation `n`."""
        return len(self.slots.get(n, [])), 2 ** (n - 1)

    @property
    def total_slots(self) -> int:
        return sum(len(v) for v in self.slots.values())

    @property
    def distinct_ancestors(self) -> int:
        return len({x for v in self.slots.values() for x in v})

    @property
    def implex(self) -> int:
        return self.total_slots - self.distinct_ancestors

    @property
    def foster_slots(self) -> dict[int, int]:
        """Generations where a `PEDI foster` link shrinks the filled count.

        {generation: how many fewer slots than the unfiltered walk}, for
        generations where the two disagree. A person raised by a family but not
        born to it still shows up one generation earlier; what disappears is
        the generation *above* them, where their non-biological parents would
        have counted.

        Empty when `estat.filiacions_que_compten` counts every filiation the
        tree has: then the two walks agree and there is nothing to explain.
        """
        out: dict[int, int] = {}
        for n in self.slots_with_foster:
            diff = len(self.slots_with_foster.get(n, [])) - len(self.slots.get(n, []))
            if diff:
                out[n] = diff
        return out

    # -- Fonts/ and the GEDCOM's references to it -------------------------

    def fonts_files(self) -> tuple[int, int, int]:
        """(originals, .md, reading copies) under Fonts/.

        Reading copies are counted apart because they are *derived*: they are
        remade from the masters by `tools.assets --lectura`, so lumping them into
        "how much is here" would double-count every scan. `MANIFEST.sha256` and any
        `.base` view definitions are not source material either: one is an
        inventory of the files, the other is a way of looking at them.
        """
        every = [
            p
            for p in FONTS.rglob("*")
            if p.is_file()
            and ".obsidian" not in p.parts
            and p.name != "MANIFEST.sha256"
            and p.suffix != ".base"
        ]
        lectura = sum(1 for p in every if p.name.endswith("_lectura.jpg"))
        return len(every) - lectura, sum(1 for p in every if p.suffix == ".md"), lectura

    def fonts_by_folder(self) -> dict[str, int]:
        """Content `.md` per archive folder -- what a folder README would otherwise restate."""
        out: dict[str, int] = {}
        for path in FONTS.rglob("*.md"):
            if ".obsidian" in path.parts or path.name.startswith("00 "):
                continue
            relative = path.relative_to(FONTS)
            folder = relative.parts[0] if len(relative.parts) > 1 else "."
            out[folder] = out.get(folder, 0) + 1
        return out

    def gedcom_paths(self) -> tuple[int, int, list[str]]:
        """(routes found, lines carrying them, routes that do not exist).

        Folder-only references are deliberately not covered -- the regex ends at
        an extension, so it skips lines that cite a directory. Those are found
        with `grep -n "Fonts/"` and looking for the ones without an extension;
        `Fonts/00 LLEGIU-ME.md` explains why.
        """
        routes = lines = 0
        broken: list[str] = []
        for raw in self.tree.ged.raw:
            hits = _FONTS_PATH.findall(raw)
            if not hits:
                continue
            lines += 1
            for route in hits:
                routes += 1
                if not (ROOT / route).exists():
                    broken.append(route)
        return routes, lines, broken

    def sosa_lines(self) -> tuple[int, int]:
        """(people with a Sosa label, total _SOSADABOVILLE lines).

        Ancestris can leak a duplicate line per save for a handful of people, so
        the second number drifting above the first is the symptom to watch.
        """
        people = sum(1 for p in self.tree.people.values() if p.sosa)
        total = sum(1 for raw in self.tree.ged.raw if raw.startswith("1 _SOSADABOVILLE"))
        return people, total


def render(estat: Estat) -> str:
    every, markdown, lectura = estat.fonts_files()
    routes, lines, broken = estat.gedcom_paths()
    labelled, sosa_total = estat.sosa_lines()
    first, last = estat.period

    out = [
        "# Estat de l'arbre",
        "",
        "**Generat per `python -m tools.estat`. No s'edita a mà.**",
        "",
        "Cap número d'aquest fitxer s'ha de copiar a cap altre lloc: es cita amb un",
        "enllaç. Copiar-los és el que fa que la mateixa xifra visqui, falsa, en cinc",
        "llocs alhora, i `tools.lint --xifres` és el que ho detecta si algú ho fa.",
        "",
        "|  |  |",
        "| --- | --- |",
        f"| Persones a l'arbre | **{estat.people}** |",
        f"| Famílies | {estat.families} |",
        f"| Amb identificador de FamilySearch | {estat.with_fsftid} |",
        f"| Sense pares (front de recerca) | {estat.without_parents} |",
        f"| Període | **{first}** – {last} |",
        "",
    ]

    if estat.root:
        out += [
            "## Caselles d'avantpassats",
            "",
            f"Recorrent els `FAMC` des de `@{estat.root}@`, **no llegint etiquetes**:",
            "l'Ancestris etiqueta cada persona amb el seu Sosa més baix i prou, o siga",
            "que comptar etiquetes subcompta l'implex.",
            "",
            "| Gen | Caselles | De |",
            "| --- | --- | --- |",
        ]
        for n in sorted(estat.slots):
            filled, possible = estat.generation(n)
            out.append(f"| G{n} | {filled} | {possible} |")

        out += [
            "",
            f"**{estat.total_slots} caselles ocupades per {estat.distinct_ancestors} "
            f"persones diferents: {estat.implex} caselles són implex.**",
            "",
        ]
        counted_extra = sorted(estat.counted - {"birth"})
        if counted_extra:
            out += [
                f"Les filiacions `2 PEDI {'`, `'.join(counted_extra)}` **hi compten**, "
                "perquè `config.yaml` ho diu a `estat.filiacions_que_compten`: qui hi "
                "consta com a criat i no com a nascut porta els avantpassats de qui el "
                "va criar. El raonament de cada cas té el seu fitxer a `Fonts/Casos/`.",
                "",
            ]
        foster = estat.foster_slots
        if foster:
            detail = ", ".join(f"G{n} en {d}" for n, d in sorted(foster.items()))
            out += [
                f"Algunes caselles compten menys del que la generació permetria "
                f"perquè una filiació hi és `2 PEDI foster`: la persona hi consta com "
                f"a criada, no com a nascuda ({detail}). El raonament de cada cas té "
                "el seu fitxer a `Fonts/Casos/`.",
                "",
            ]

    out += [
        "## Fonts",
        "",
        "|  |  |",
        "| --- | --- |",
        f"| Fitxers a `Fonts/` | **{every}**, dels quals **{markdown}** `.md` |",
        f"| Còpies de lectura (derivades) | {lectura} |",
        f"| Rutes de `Fonts/` citades al GEDCOM | **{routes}** en {lines} línies, "
        f"{len(broken)} trencades |",
        f"| Persones amb etiqueta Sosa | {labelled} de {estat.people} |",
        f"| Línies `_SOSADABOVILLE` | {sosa_total} |",
        "",
        "Documents per carpeta, sense comptar els `00 LLEGIU-ME.md`:",
        "",
        "| Carpeta | Documents |",
        "| --- | --- |",
    ]
    for folder, n in sorted(estat.fonts_by_folder().items()):
        out.append(f"| `{folder}/` | {n} |")

    if broken:
        out += ["", "## Rutes trencades", ""]
        out += [f"- `{route}`" for route in broken]

    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--print", action="store_true", help="to stdout, write nothing")
    args = parser.parse_args(argv)

    estat = Estat(Path(args.canonical) if args.canonical else None)
    text = render(estat)

    if args.print:
        print(text, end="")
        return 0

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "estat.md"
    out.write_text(text, encoding="utf-8")
    g6, _ = estat.generation(6)
    g7, _ = estat.generation(7)
    print(f"{estat.people} persones, {estat.families} famílies, "
          f"G6 {g6}/32, G7 {g7}/64")
    print(f"{estat.total_slots} caselles, {estat.distinct_ancestors} persones, "
          f"{estat.implex} implex")
    routes, lines, broken = estat.gedcom_paths()
    print(f"{routes} rutes de Fonts/ en {lines} línies, {len(broken)} trencades")
    print(f"wrote {out.relative_to(ROOT)}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())

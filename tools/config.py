"""Where the family-specific settings live, so that the code holds none.

Everything that changes from one family to the next -- which file is the tree,
which FamilySearch profile to start from, which towns belong to which archive --
is in `config.yaml` at the root of the repository. Every tool reads it through
here, so a new user edits one file and never has to open the Python.

The rule this module exists to enforce: **no personal name, xref or place is
hard-coded anywhere under `tools/`.** If you find yourself about to write one,
it belongs in `config.yaml`.

    from .config import tree_path
    ged = GedcomFile(tree_path())
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

def _find_root() -> Path:
    """The repository being worked on -- which is not where this code lives.

    These tools are installed as a package (`genealogia-tools`), so
    `Path(__file__).parents[1]` is `site-packages`, and every path derived from
    it -- `config.yaml`, `Fonts/`, `reports/`, `cache/` -- would point inside
    the virtualenv instead of at the family's repository. It looked right for
    as long as the tools were copied into each repository, which is exactly the
    duplication the package exists to end.

    So the root is found the way git finds one: from the working directory
    upward, looking for the file that marks a repository as configured. Set
    `GENEALOGIA_ARREL` to override it -- useful from an editor, or from a
    scheduled job whose working directory is not the repository.
    """
    override = os.environ.get("GENEALOGIA_ARREL")
    if override:
        return Path(override).expanduser().resolve()
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / "config.yaml").exists():
            return candidate
    # Running from a checkout that has not been configured yet: the repository
    # around this file is still the best answer available.
    packaged = Path(__file__).resolve().parents[1]
    if (packaged / "config.yaml").exists():
        return packaged
    return here


ROOT = _find_root()
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_TREE = ROOT / "exemple.ged"

# The same tree, shipped inside the package. The tests pin real numbers against
# it, so they have to find it wherever the package is installed -- in a family
# repository there is no `exemple.ged` at the root, and without this copy every
# value test would simply skip and report nothing wrong.
PACKAGED_EXAMPLE = Path(__file__).resolve().parent / "tests" / "exemple.ged"


def example_tree() -> Path:
    """The example tree: the repository's own if there is one, else the packaged copy."""
    return EXAMPLE_TREE if EXAMPLE_TREE.exists() else PACKAGED_EXAMPLE


class ConfigError(SystemExit):
    """A configuration problem the user has to fix, phrased as an instruction.

    Deriving from SystemExit rather than Exception is deliberate: these are not
    conditions any caller can recover from, and a traceback would bury the one
    line that says what to edit.
    """


@lru_cache(maxsize=1)
def load() -> dict:
    """The whole of `config.yaml`, or an empty dict if there is none."""
    if not CONFIG_PATH.exists():
        raise ConfigError(
            f"no hi ha {CONFIG_PATH.name} a {ROOT}. És el fitxer que diu quin és el "
            "teu arbre i quins són els teus arxius; el repositori en porta un amb "
            "tot comentat. Si l'has esborrat, recupera'l amb «git checkout config.yaml»."
        )
    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_PATH.name} ha de ser un diccionari, no {type(data).__name__}")
    return data


def get(*keys, default=None):
    """Nested lookup: `get("familysearch", "arrel")`.

    An empty string in the YAML counts as unset, because that is what a
    half-filled template looks like and treating it as a value produces
    confusing failures much further downstream.
    """
    node = load()
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    if node is None or node == "":
        return default
    return node


def _is_backup(path: Path) -> bool:
    """`Arbre_20260730-101500.ged` is a backup, `Arbre.ged` is the tree."""
    stem = path.stem
    if "_" not in stem:
        return False
    tail = stem.rsplit("_", 1)[1]
    return len(tail) == 15 and tail[:8].isdigit() and tail[8] == "-" and tail[9:].isdigit()


def candidate_trees() -> list[Path]:
    """Every `.ged` at the root that is not a backup and not the example."""
    return sorted(
        p for p in ROOT.glob("*.ged")
        if not _is_backup(p) and p.name != EXAMPLE_TREE.name
    )


def tree_path() -> Path:
    """The file that counts. Explicit in config, or the only `.ged` there is.

    Auto-detection is a convenience for the common case -- one tree exported
    from Ancestris, sitting at the root -- but it refuses to guess between two
    files. Guessing wrong here means writing proposals into the wrong tree.
    """
    configured = get("arbre")
    if configured:
        path = ROOT / configured
        if not path.exists():
            raise ConfigError(
                f"el config.yaml diu «arbre: {configured}» i aquest fitxer no hi és. "
                f"Fitxers .ged que hi ha a {ROOT}: "
                + (", ".join(p.name for p in sorted(ROOT.glob("*.ged"))) or "cap")
            )
        return path

    found = candidate_trees()
    if len(found) == 1:
        return found[0]
    if not found:
        if EXAMPLE_TREE.exists():
            return EXAMPLE_TREE
        raise ConfigError(
            "no hi ha cap .ged. Exporta l'arbre d'Ancestris, desa'l a l'arrel del "
            "repositori i posa'n el nom al config.yaml, a «arbre:»."
        )
    raise ConfigError(
        "hi ha més d'un .ged i el config.yaml no diu quin és el bo — "
        f"{', '.join(p.name for p in found)}. Posa'n el nom a «arbre:»."
    )


def fs_dump_path() -> Path | None:
    """An old GEDCOM export from FamilySearch, to match the tree against.

    Optional, and the tools that use it degrade to live data without it, so this
    returns None rather than raising when it is unset or missing.
    """
    configured = get("exportacio_familysearch")
    if not configured:
        return None
    path = ROOT / configured
    return path if path.exists() else None


def fs_root() -> str:
    """The FamilySearch PID to fetch ancestry from: usually the de-cujus.

    Start from whoever's tree you actually want covered on both sides. Rooting
    at yourself gives your parents' two halves; rooting at a child gives theirs.
    """
    pid = get("familysearch", "arrel")
    if not pid:
        raise ConfigError(
            "cal un identificador de FamilySearch per començar. Obri el perfil de la "
            "persona per qui vols arrencar l'arbre, copia el PID de la URL "
            "(la forma és XXXX-XXX) i posa'l al config.yaml, a «familysearch: arrel:»."
        )
    return str(pid)


def user_agent(component: str) -> str:
    """Identify ourselves to the archives, with a way to be contacted.

    Not decoration: an archive that can see who is making the requests and why
    can ask us to stop instead of blocking the whole range. If `contacte` is
    unset we still say what the software is, but filling it in is the polite
    thing and costs nothing.
    """
    name = get("projecte", default="genealogia")
    contact = get("contacte")
    who = f"; {contact}" if contact else ""
    return f"{name}-{component}/0.1 (recerca genealògica personal{who})"


def regions() -> dict[str, set[str]]:
    """archive cluster -> its towns, normalised the same way a PLAC is.

    Normalising through `norm_place_component` and not merely `fold` matters:
    it is what turns "La Bisbal d'Empordà" into "la bisbal d emporda", which is
    the shape `Person.birth_town` comes back in. Comparing folded-but-not-
    depunctuated names silently matches nothing for every town with an
    apostrophe or a hyphen in it, and those are not rare here.
    """
    from .normalize import norm_place_component

    out: dict[str, set[str]] = {}
    for name, towns in (get("regions", default={}) or {}).items():
        out[name] = {norm_place_component(t) for t in (towns or []) if t}
    return out


def region_guides() -> dict[str, dict]:
    """Per-region prose and links for the worklist report."""
    guides = dict(get("guies", default={}) or {})
    guides.setdefault("unknown", {
        "title": "Sense lloc de naixement",
        "blurb": (
            "Aquestes persones no tenen lloc de naixement al GEDCOM, i sense lloc no "
            "es pot cercar en cap arxiu. El primer pas no és buscar-les a elles sinó "
            "mirar on es van casar o on van néixer els seus fills, que sí que "
            "consten, i començar per aquella parròquia."
        ),
        "links": [],
        "extra": "",
    })
    for guide in guides.values():
        guide.setdefault("title", "(sense títol)")
        guide.setdefault("blurb", "")
        guide.setdefault("links", [])
        guide.setdefault("extra", "")
        # YAML gives links as {label: url} pairs; the report wants tuples.
        if isinstance(guide["links"], dict):
            guide["links"] = list(guide["links"].items())
        else:
            guide["links"] = [
                tuple(l) if isinstance(l, (list, tuple)) else (str(l), str(l))
                for l in guide["links"]
            ]
    return guides


def apv_floor() -> str | None:
    """The deepest person whose filiation a document already confirms.

    `tools.apv.verify` walks upward from here, and the whole point of naming it
    explicitly rather than deriving it is to state where documented ground ends.
    Unset means "start from the de-cujus", which is a fine place to start.
    """
    floor = get("apv", "terra_documentada")
    return str(floor) if floor else None


def apv_parish_rules() -> list[dict]:
    """Which parish would have recorded a sacrament for someone born where.

    A birth place is not a parish, and the two diverge on purpose: a hamlet with
    no church of its own has its baptisms in the mother parish's books until the
    year it got them. That year is per-place history, so it lives in the config.
    """
    return list(get("apv", "parroquies", default=[]) or [])


def apv_default_parish() -> str:
    """Where to look when nothing in the tree says otherwise."""
    return str(get("apv", "parroquia_per_defecte", default="") or "")


def marriage_age() -> int:
    """Birth + this = the marriage-year estimate, when no MARR event exists.

    A genealogical assumption, and it varies by place and period, so it is a
    setting and not a constant. See `tools.apv.verify._marriage_year` for why
    the eldest known child is a ceiling and never the anchor.
    """
    return int(get("apv", "edat_de_casar", default=24))


def region_fallbacks() -> list[tuple[str, str]]:
    """(text to look for in the birth place, region) when the town is unknown.

    Coarser than the town lists and checked after them: a place that says
    "Girona" somewhere is probably Girona even if the town is new to us.
    """
    raw = get("regions_per_defecte", default={}) or {}
    return [(str(k).lower(), str(v)) for k, v in raw.items()]


UNPLACED = "unknown"  # no birth place, so no archive to go to


def region_for(town: str, place: str) -> str:
    """Which archive cluster a person belongs to. The one place that decides it.

    `town` is a `Person.birth_town` (already normalised) and `place` the raw
    PLAC folded. Both tools that group by archive -- the worklist and the
    frontier ranking -- come through here, so they can never disagree.
    """
    if not place and not town:
        return UNPLACED
    haystack = town or place
    for name, towns in regions().items():
        if haystack in towns or any(t in haystack for t in towns):
            return name
    for needle, name in region_fallbacks():
        if needle in place:
            return name
    return UNPLACED


def estat_root() -> str | None:
    """The xref to count ancestor generations from, for `tools.estat`.

    Unset means "the person with `_SOSADABOVILLE 1`" -- the de cuius that
    Ancestris itself designates -- which is the right default for the common
    case of counting one person's own ancestry and needs no editing.
    """
    root = get("estat", "arrel")
    return str(root) if root else None


def frontmatter_archives() -> dict[str, str]:
    """`Fonts/` short code -> the archive's full name, for `tools.frontmatter`.

    Empty until you fill it in. `tools.frontmatter --check` only validates a
    note's `arxiu:` key against this list once it has entries, so the template
    does not reject anything before you have decided what to call your own
    archives.
    """
    raw = get("frontmatter", "arxius", default={}) or {}
    return {str(k): str(v) for k, v in raw.items()}


def archive_hint(town: str, place: str) -> tuple[int, str]:
    """How reachable this town's registers are (0-5), and a line saying where.

    The score feeds the frontier ranking, and it is a judgement about **access,
    not about the family**: a parish whose books are online is worth attacking
    before one that needs a letter and a wait, whoever is in it. Per-region by
    default, with `arxius:` for the town that is an exception -- a hamlet whose
    registers sit in another parish's books, typically.
    """
    from .normalize import norm_place_component

    overrides = get("arxius", default={}) or {}
    key = town or ""
    for name, spec in overrides.items():
        if norm_place_component(name) == key:
            return int(spec.get("puntuacio", 0)), str(spec.get("nota", ""))

    region = region_for(town, place)
    guide = (get("guies", default={}) or {}).get(region) or {}
    note = str(guide.get("nota") or guide.get("title") or "")
    return int(guide.get("puntuacio", 0)), note


def apv_archive_sources() -> set[str]:
    """SOUR xrefs that count as archive evidence for `tools.apv.verify`.

    Someone already carrying one of these has been documented by an archive and
    is not worth a query. FamilySearch and any family summary are deliberately
    NOT in here by default: they are exactly what the index is being checked
    against, and counting them would retire the ancestors most in need of proof.
    """
    raw = get("apv", "fonts_arxiu", default=[]) or []
    return {str(x).strip().strip("@") for x in raw if str(x).strip()}


def apv_archive_folders() -> tuple[str, ...]:
    """Folders of `Fonts/` whose `.md` files are archive transcriptions.

    A person named in one of them has been looked up already, whether or not
    the GEDCOM says so -- a citation gets hung on the person searched for and
    not on everyone the document names, and the difference costs a query.
    """
    raw = get("apv", "carpetes_arxiu", default=[]) or []
    return tuple(str(x) for x in raw if str(x).strip())


def apv_lost_marriage_books() -> tuple[tuple[str, int, int], ...]:
    """(parish, from, to) spans whose marriage books are LOST.

    Where the book is gone, what the index holds is the gutting of an index
    book: one surname per person and the father of the interested party alone,
    with no image to request afterwards. That changes the ORDER a plan should
    propose things in -- a marriage there yields one name where a baptism from
    a surviving book yields seven -- so it is worth stating per parish.
    """
    out = []
    for entry in get("apv", "llibres_perduts", default=[]) or []:
        if not isinstance(entry, dict):
            continue
        parish = str(entry.get("parroquia", "")).lower().strip()
        start, end = entry.get("de"), entry.get("a")
        if parish and start is not None and end is not None:
            out.append((parish, int(start), int(end)))
    return tuple(out)


def apv_branches() -> tuple[tuple[int, str], ...]:
    """(Sosa number, region) roots that say which branch an ancestor is on.

    Sosa numbering already encodes the branch: halving a Sosa number walks down
    a generation, so halving repeatedly lands on the ancestor whose side the
    person is on. Deciding the archive that way beats reading birth places one
    by one, which fails for everyone whose PLAC is empty.

    Order matters and is kept: the narrowest branch has to be checked first,
    because it sits inside a wider one.
    """
    out = []
    for entry in get("apv", "branques", default=[]) or []:
        if isinstance(entry, dict) and entry.get("sosa"):
            out.append((int(entry["sosa"]), str(entry.get("regio", ""))))
    return tuple(out)


def apv_index_regions() -> set[str]:
    """Regions this index actually holds. Others have their own archives.

    Empty means "no branch rule configured", and `tools.apv.verify` then
    considers every ancestor rather than silently planning nothing.
    """
    raw = get("apv", "regions_amb_index", default=[]) or []
    return {str(x) for x in raw if str(x).strip()}


def generation_years() -> int:
    """Years between a birth and the next one down, for estimating dates.

    Used when an ancestor has no date of their own and the only anchor is a
    dated descendant. The estimate leans late -- a tree of ancestors records
    the child we descend from, rarely the firstborn -- so callers widen their
    search window per hop rather than trusting this number.
    """
    return int(get("apv", "anys_per_generacio", default=30))

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

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_TREE = ROOT / "exemple.ged"


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

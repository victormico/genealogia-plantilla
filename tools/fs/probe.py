"""Probe which FamilySearch endpoints this app key can actually reach.

Some endpoints are restricted to certified applications and simply return 403.
Rather than discover that mid-research, find out once and record it. Run:

    python3 -m tools.fs.probe
"""

from __future__ import annotations

import argparse
import sys

from .. import config
from .api import Api
from .session import add_common_args, build_session


EXPLAIN = {
    204: "no results",
    403: "forbidden — app not certified for this",
    404: "not found",
}


# Cal un avantpassat DIFUNT per a les comprovacions que un registre de persona viva
# no pot contestar. Es posa al config.yaml, a «familysearch: prova_difunt:».
#
# Fa falta perquè aquesta sonda ens va enganyar. Provava `sources` contra el registre
# de qui inicia la sessió —una persona viva, sense cap font adjunta— i en treia
# "UNAVAILABLE", i d'allà vam concloure que l'endpoint estava tancat per certificació.
# No ho està: contra un difunt amb fonts va tornar 23 fonts adjuntes, i entre elles hi
# havia l'ARK de la imatge d'una partida que ja havíem anat a buscar a mà a l'arxiu.
#
# La lliçó és de la sonda, no de l'API: **una comprovació que es fa contra el subjecte
# equivocat no dona un "no", dona un "no ho sé" disfressat de "no".**


def summarise(label: str, data: dict | None, fs=None, path: str = "") -> str:
    if data is None:
        why = ""
        if fs is not None:
            status = next(
                (s for p, s in reversed(list(fs.last_status.items())) if path in p),
                None,
            )
            if status:
                why = f" [{status}: {EXPLAIN.get(status, '')}]"
        return f"  UNAVAILABLE  {label}{why}"
    # Les fonts adjuntes venen com a persons[].sources[], o siga que la resposta porta
    # «persons» i el branch de sota se la menjaria i diria «1 person(s), first = ?».
    # Cal exigir també sourceDescriptions: la resposta d'`ancestry` porta persones amb
    # fonts a dins i no és una llista de fonts.
    descs = len(data.get("sourceDescriptions") or [])
    attached = sum(len(p.get("sources") or []) for p in data.get("persons") or [])
    if attached and descs:
        return f"  ok           {label}: {attached} attached source(s), {descs} description(s)"
    if "persons" in data:
        n = len(data["persons"])
        first = data["persons"][0]
        name = (first.get("display", {}) or {}).get("name", "?")
        return f"  ok           {label}: {n} person(s), first = {name}"
    if "entries" in data:
        return f"  ok           {label}: {len(data['entries'])} entr(ies)"
    if "sourceDescriptions" in data:
        return f"  ok           {label}: {len(data['sourceDescriptions'])} source(s)"
    if "places" in data:
        return f"  ok           {label}: {len(data['places'])} place(s)"
    keys = ", ".join(sorted(data)[:6])
    return f"  ok           {label}: keys = {keys}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.add_argument("--pid", help="person to probe against [your own]")
    parser.add_argument(
        "--dead-pid",
        default=None,
        help="a DECEASED person, for the checks that a living record cannot answer "
        "[familysearch: prova_difunt, from config.yaml]",
    )
    parser.add_argument("--surname", default=None, help="a surname to test the searches with")
    parser.add_argument("--place", default=None, help="a place to test the searches with")
    args = parser.parse_args()

    fs = build_session(args)
    api = Api(fs)
    pid = args.pid or fs.fid
    dead = args.dead_pid or config.get("familysearch", "prova_difunt")
    # Something to put in the search boxes. Any surname reaches the endpoint;
    # one of your own just makes the output readable.
    probe_surname = args.surname or fs.display_name.split()[-1]
    probe_place = args.place or "Girona, Espanya"
    print(f"probing as {fs.display_name} ({fs.fid}) against {pid}")
    if dead:
        print(f"  (sources probed against {dead}, a deceased person -- see the note in this file)\n")
    else:
        print(
            "  (sense «familysearch: prova_difunt» al config.yaml, la comprovació de\n"
            "   fonts va contra tu mateix, que és justament el subjecte equivocat:\n"
            "   vegeu la nota d'aquest fitxer)\n"
        )
        dead = pid

    checks = [
        ("person", lambda: api.person(pid), "persons/"),
        ("ancestry (8 gens)", lambda: api.ancestry(pid, generations=8), "ancestry"),
        ("parents", lambda: api.parents(pid), "/parents"),
        ("spouses", lambda: api.spouses(pid), "/spouses"),
        ("sources (against a deceased person)", lambda: api.sources(dead), "/sources"),
        ("duplicates (ungated matches)", lambda: api.duplicates(pid), "/matches"),
        ("record hints (needs certification)", lambda: api.record_hints(pid), "/matches"),
        (
            "tree search",
            lambda: api.tree_search(surname=probe_surname, count=5),
            "tree/search",
        ),
        (
            "records search",
            lambda: api.records_search(
                surname=probe_surname, birth_like_place=probe_place, count=5
            ),
            "records/personas",
        ),
        (
            "place authority",
            lambda: api.place_search(probe_place.split(",")[0] or "Girona"),
            "places/search",
        ),
    ]
    for label, call, path in checks:
        try:
            print(summarise(label, call(), fs, path))
        except Exception as exc:  # a probe must report, not abort
            print(f"  ERROR        {label}: {type(exc).__name__}: {exc}")

    print(f"\n{fs.stats()}")
    if fs.forbidden:
        print("\nforbidden (app not certified for these):")
        for path in sorted(fs.forbidden):
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

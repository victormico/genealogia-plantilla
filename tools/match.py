"""Match the canonical tree against the FamilySearch dump and propose _FSFTID.

The FamilySearch person ID is the join key everything else needs: with it, a
person in the canonical tree can be handed straight to the API. The dump on
disk already carries one for all 235 of its people, so this match costs no
requests at all.

    python3 -m tools.match                 # write the report and the proposals
    python3 -m tools.match --explain I00047  # show the scoring for one person

Output:
    reports/match-report.md        the four buckets, for reading
    reports/fsftid-backfill.yaml   proposals with accept: for tools/apply.py
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import report
from .config import fs_dump_path, tree_path
from .people import Person, Tree
from .normalize import fold, given_match, place_match, year_match

ROOT = Path(__file__).resolve().parents[1]
PEDIGREE = ROOT / "cache" / "pedigree.json"
REPORTS = ROOT / "reports"

# Weights. Surname carries the most because Spanish and Catalan double surnames
# are highly identifying: "ASENSI GIRONÉS" narrows a parish to a family.
W_SURNAME = 3.0
W_GIVEN = 2.5
W_BIRTH_YEAR = 2.0
W_BIRTH_PLACE = 1.5
W_DEATH_YEAR = 1.0
W_SEX = 0.5
W_RELATIVES = 2.0  # a shared parent or spouse surname

CONFIDENT = 7.0  # accept without asking
PLAUSIBLE = 4.5  # worth a human look
MARGIN = 1.5  # a confident match must also beat the runner-up by this much


@dataclass
class Score:
    total: float
    reasons: list[str]

    def __lt__(self, other: "Score") -> bool:
        return self.total < other.total


@dataclass
class Candidate:
    fs: Person
    score: Score


def surname_score(a: Person, b: Person) -> tuple[float, str | None]:
    pa, pb = a.surname_parts, b.surname_parts
    if not pa or not pb:
        return 0.0, None
    if pa == pb:
        return W_SURNAME, f"surname identical ({' '.join(pa)})"
    shared = [p for p in pa if p in pb]
    if not shared:
        return 0.0, None
    # The paternal surname comes first in both traditions; agreeing on it is
    # much stronger evidence than agreeing on the maternal one.
    if pa[0] == pb[0]:
        if len(pa) > 1 and len(pb) > 1 and pa[1] != pb[1]:
            # Both sources record a maternal surname and they disagree: that is
            # evidence of two different people, not a spelling variant.
            # "FERRER SANTONJA" vs "Ferrer Pastor" must not read as a match.
            return (
                W_SURNAME * 0.4,
                f"paternal surname matches ({pa[0]}) but maternal differs "
                f"({pa[1]} / {pb[1]})",
            )
        return W_SURNAME * 0.75, f"paternal surname matches ({pa[0]})"
    return W_SURNAME * 0.4, f"one surname shared ({shared[0]})"


def score_pair(canon: Person, fs: Person, canon_tree: Tree, fs_tree: Tree) -> Score:
    total = 0.0
    reasons: list[str] = []

    points, why = surname_score(canon, fs)
    total += points
    if why:
        reasons.append(why)

    g = given_match(canon.given, fs.given)
    if g:
        total += W_GIVEN * g
        reasons.append(
            f"given name {'identical' if g == 1.0 else 'variant'} "
            f"({canon.given} / {fs.given})"
        )

    y = year_match(canon.birth_year, fs.birth_year)
    if y:
        total += W_BIRTH_YEAR * y
        same = canon.birth_year == fs.birth_year
        reasons.append(
            f"birth year {'matches' if same else 'close'} "
            f"({canon.birth_year} / {fs.birth_year})"
        )
    elif canon.birth_year and fs.birth_year:
        # Both known and far apart: real evidence against, not just absence.
        gap = abs(canon.birth_year - fs.birth_year)
        if gap > 40:
            # More than a generation and a half apart cannot be one person, no
            # matter how well the names agree.
            total -= 8.0
            reasons.append(
                f"birth years {gap}y apart — different people "
                f"({canon.birth_year} / {fs.birth_year})"
            )
        elif gap > 10:
            total -= 2.0
            reasons.append(f"birth years {gap}y apart ({canon.birth_year} / {fs.birth_year})")

    p = place_match(canon.birth_place, fs.birth_place)
    if p:
        total += W_BIRTH_PLACE * p
        reasons.append(f"birthplace {'matches' if p == 1.0 else 'nearby'} ({canon.birth_town})")

    d = year_match(canon.death_year, fs.death_year)
    if d:
        total += W_DEATH_YEAR * d
        reasons.append(f"death year matches ({canon.death_year})")

    if canon.sex and fs.sex:
        if canon.sex == fs.sex:
            total += W_SEX
        else:
            total -= 3.0
            reasons.append(f"sex differs ({canon.sex} / {fs.sex})")

    # Relatives: agreeing on a parent's or spouse's surname is strong.
    canon_rel = {fold(r.norm_surname) for r in canon_tree.parents(canon.xref)} | {
        fold(r.norm_surname) for r in canon_tree.spouses(canon.xref)
    }
    fs_rel = {fold(r.norm_surname) for r in fs_tree.parents(fs.xref)} | {
        fold(r.norm_surname) for r in fs_tree.spouses(fs.xref)
    }
    shared_rel = {r for r in canon_rel & fs_rel if r}
    if shared_rel:
        total += W_RELATIVES
        reasons.append(f"shares a relative surname ({sorted(shared_rel)[0]})")

    return Score(round(total, 2), reasons)


@dataclass
class Match:
    canon: Person
    best: Candidate | None
    runner_up: Candidate | None
    bucket: str  # confident | review | unmatched
    # Set when the top candidate was already claimed by a stronger match. The
    # rejected candidate is still worth showing: it explains the outcome.
    lost_to: str | None = None

    @property
    def fsftid(self) -> str | None:
        return self.best.fs.fsftid if self.best else None


def block_key(person: Person) -> str:
    """Cheap blocking key so we do not score all 175x235 pairs blindly."""
    parts = person.surname_parts
    return parts[0] if parts else ""


def match_trees(canon_tree: Tree, fs_tree: Tree) -> list[Match]:
    # Block on paternal surname, but always also consider people whose *other*
    # surname matches, since the sources occasionally swap or drop one.
    by_first: dict[str, list[Person]] = {}
    by_any: dict[str, list[Person]] = {}
    for p in fs_tree.people.values():
        parts = p.surname_parts
        if parts:
            by_first.setdefault(parts[0], []).append(p)
        for part in parts:
            by_any.setdefault(part, []).append(p)

    # Score every plausible pair, keeping the full ranked candidate list per
    # person: the assignment step below needs to walk past claimed candidates.
    ranked: list[tuple[Person, list[Candidate]]] = []
    for canon in canon_tree.people.values():
        pool: dict[str, Person] = {}
        for part in canon.surname_parts:
            for cand in by_any.get(part, ()):
                pool[cand.xref] = cand
        candidates = [
            Candidate(fs, score_pair(canon, fs, canon_tree, fs_tree))
            for fs in pool.values()
        ]
        candidates.sort(key=lambda c: c.score.total, reverse=True)
        ranked.append((canon, candidates))

    # One-to-one assignment: the strongest pairs claim their FamilySearch person
    # first, so a good match is never stolen by a weaker one. A person whose top
    # candidate is already claimed walks down its own list to the best free one.
    ranked.sort(key=lambda row: -(row[1][0].score.total if row[1] else 0.0))
    claimed: dict[str, str] = {}
    results: dict[str, Match] = {}
    for canon, candidates in ranked:
        top = candidates[0] if candidates else None
        free = [c for c in candidates if c.fs.xref not in claimed]
        best = free[0] if free else None
        runner = free[1] if len(free) > 1 else None
        lost_to = None
        if best is None or (top is not None and best is not top):
            lost_to = claimed.get(top.fs.xref) if top else None

        if best is None:
            results[canon.xref] = Match(canon, top, None, "unmatched", lost_to)
            continue

        gap = best.score.total - (runner.score.total if runner else 0.0)
        if best.score.total >= CONFIDENT and gap >= MARGIN:
            bucket = "confident"
        elif best.score.total >= PLAUSIBLE:
            bucket = "review"
        else:
            results[canon.xref] = Match(canon, best, runner, "unmatched", lost_to)
            continue
        claimed[best.fs.xref] = canon.xref
        results[canon.xref] = Match(canon, best, runner, bucket, lost_to)

    for canon in canon_tree.people.values():
        results.setdefault(canon.xref, Match(canon, None, None, "unmatched"))
    return [results[x] for x in canon_tree.people]


# -- reporting ------------------------------------------------------------


def source_label(tree) -> str:
    """Where the FamilySearch side came from: a file on disk or the live tree."""
    ged = getattr(tree, "ged", None)
    if ged is not None:
        return f"`{ged.path.name}`"
    return f"arbre en línia de FamilySearch, arrel {getattr(tree, 'root', '?')}"


def write_report(matches: list[Match], canon_tree: Tree, fs_tree, path: Path) -> None:
    confident = [m for m in matches if m.bucket == "confident"]
    review = [m for m in matches if m.bucket == "review"]
    unmatched = [m for m in matches if m.bucket == "unmatched"]
    claimed = {m.best.fs.xref for m in matches if m.best and m.bucket != "unmatched"}
    fs_only = [p for p in fs_tree.people.values() if p.xref not in claimed]

    lines = [
        "# Correspondència entre l'arbre principal i l'exportació de FamilySearch",
        "",
        f"- Arbre principal: **{len(canon_tree.people)}** persones "
        f"(`{canon_tree.ged.path.name}`)",
        f"- FamilySearch: **{len(fs_tree.people)}** persones "
        f"({source_label(fs_tree)})",
        "",
        f"| Grup | Persones |",
        f"| --- | --- |",
        f"| Correspondència segura (s'aplica sola) | **{len(confident)}** |",
        f"| Cal revisar-ho a mà | **{len(review)}** |",
        f"| Només a l'arbre principal | **{len(unmatched)}** |",
        f"| Només a FamilySearch | **{len(fs_only)}** |",
        "",
        "La puntuació suma cognom (3), nom (2,5), any de naixement (2), lloc de",
        "naixement (1,5), any de defunció (1), sexe (0,5) i cognom d'un familiar",
        "(2). Es considera segura a partir de 7 punts i amb 1,5 punts d'avantatge",
        "sobre la segona opció.",
        "",
    ]

    def table(rows: list[Match], title: str, note: str = "") -> None:
        lines.append(f"## {title} ({len(rows)})")
        if note:
            lines.extend(["", note])
        lines.extend(
            [
                "",
                "| Arbre principal | Naixement | FamilySearch | Naixement | Punts | Per què |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for m in sorted(rows, key=lambda r: -(r.best.score.total if r.best else 0)):
            assert m.best
            c, f = m.canon, m.best.fs
            lines.append(
                f"| @{c.xref}@ {c.given} {c.surname} | {c.birth_date or '?'} "
                f"{c.birth_town or ''} | [{f.fsftid}]"
                f"(https://www.familysearch.org/tree/person/details/{f.fsftid}) "
                f"{f.given} {f.surname} | {f.birth_date or '?'} {f.birth_town or ''} "
                f"| {m.best.score.total} | {'; '.join(m.best.score.reasons)} |"
            )
        lines.append("")

    table(confident, "Correspondència segura")
    table(
        review,
        "Cal revisar-ho a mà",
        "Posa `accept: true` o `false` a `reports/fsftid-backfill.yaml` per a cada "
        "cas. Les diferències d'any solen venir de dates estimades introduïdes com "
        "si fossin exactes.",
    )

    lines.append(f"## Només a l'arbre principal ({len(unmatched)})")
    lines.extend(
        [
            "",
            "Aquestes persones no són a FamilySearch, o hi són amb un nom prou",
            "diferent per no trobar-les. Són candidates a crear-hi-les.",
            "",
            "| Arbre principal | Naixement | Lloc | Millor opció descartada |",
            "| --- | --- | --- | --- |",
        ]
    )
    for m in sorted(unmatched, key=lambda r: r.canon.xref):
        c = m.canon
        near = ""
        if m.best:
            near = (
                f"{m.best.fs.given} {m.best.fs.surname} "
                f"({m.best.fs.birth_year or '?'}) — {m.best.score.total} punts"
            )
        lines.append(
            f"| @{c.xref}@ {c.given} {c.surname} | {c.birth_date or '?'} "
            f"| {c.birth_town or '?'} | {near} |"
        )

    lines.extend(
        [
            "",
            f"## Només a FamilySearch ({len(fs_only)})",
            "",
            "Persones de l'exportació que no són a l'arbre principal. Moltes són",
            "avantpassats que amplien branques existents: candidates a importar-les",
            "un cop revisada la correspondència.",
            "",
            "| FamilySearch | Nom | Naixement | Lloc | Fonts |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for p in sorted(
        fs_only, key=lambda q: (-q.source_count, q.birth_year or 9999)
    ):
        lines.append(
            f"| [{p.fsftid}](https://www.familysearch.org/tree/person/details/{p.fsftid}) "
            f"| {p.given} {p.surname} | {p.birth_date or '?'} | {p.birth_town or '?'} "
            f"| {p.source_count} |"
        )

    lines.extend(hygiene_section(canon_tree))
    report.write(path, "\n".join(lines) + "\n")


def hygiene_section(canon_tree: Tree) -> list[str]:
    """Couples sharing identical vital years: estimates entered as exact dates.

    Reported only. Nothing is changed: deciding that a year is an estimate is a
    genealogical judgement, and the file currently uses no ABT qualifier at all.
    """
    suspects = []
    for fam in canon_tree.families.values():
        if not (fam.husband and fam.wife):
            continue
        h = canon_tree.people.get(fam.husband)
        w = canon_tree.people.get(fam.wife)
        if not h or not w:
            continue
        same_birth = h.birth_year and h.birth_year == w.birth_year
        same_death = h.death_year and h.death_year == w.death_year
        if same_birth or same_death:
            suspects.append((fam.xref, h, w, same_birth, same_death))

    out = [
        "",
        f"## Dates que semblen estimacions ({len(suspects)} parelles)",
        "",
        "Parelles amb el mateix any de naixement o de defunció. Molt probablement",
        "són estimacions introduïdes com si fossin dates exactes. El fitxer no fa",
        "servir cap qualificador `ABT` enlloc, així que la informació de «cap a»",
        "s'ha perdut. No s'hi toca res: decidir si un any és una estimació és una",
        "valoració genealògica.",
        "",
        "| Família | Marit | Muller | Coincideix |",
        "| --- | --- | --- | --- |",
    ]
    for xref, h, w, same_birth, same_death in sorted(suspects, key=lambda s: s[0]):
        what = ", ".join(
            filter(None, ["naixement" if same_birth else "", "defunció" if same_death else ""])
        )
        out.append(
            f"| @{xref}@ | {h.given} {h.surname} ({h.birth_year or '?'}–"
            f"{h.death_year or '?'}) | {w.given} {w.surname} ({w.birth_year or '?'}–"
            f"{w.death_year or '?'}) | {what} |"
        )
    return out


def write_proposals(matches: list[Match], path: Path) -> int:
    """YAML proposals for tools/apply.py. Confident ones are pre-accepted."""
    out = [
        f"# Propostes per escriure _FSFTID a «{tree_path().name}».",
        "#",
        "# accept: true   -> s'afegeix «1 _FSFTID <id>» a aquesta persona",
        "# accept: false  -> s'ignora",
        "# accept: null   -> pendent de decidir (no s'aplica)",
        "#",
        "# Les correspondències segures ja venen amb accept: true. Revisa la resta",
        "# comparant-les a reports/match-report.md i, si cal, obrint l'enllaç.",
        "",
    ]
    count = 0
    for m in matches:
        if m.bucket == "unmatched" or not m.best:
            continue
        c, f = m.canon, m.best.fs
        accept = "true" if m.bucket == "confident" else "null"
        out.extend(
            [
                f"- target: \"{c.xref}\"",
                f"  # {c.given} {c.surname}, n. {c.birth_date or '?'} "
                f"{c.birth_town or ''}".rstrip(),
                f"  # FamilySearch: {f.given} {f.surname}, n. {f.birth_date or '?'} "
                f"{f.birth_town or ''}".rstrip(),
                f"  # https://www.familysearch.org/tree/person/details/{f.fsftid}",
                f"  # {m.best.score.total} punts: {'; '.join(m.best.score.reasons)}",
                f"  fsftid: \"{f.fsftid}\"",
                f"  confidence: {m.bucket}",
                f"  accept: {accept}",
                "",
            ]
        )
        count += 1
    path.write_text("\n".join(out), encoding="utf-8")
    return count


def explain(xref: str, canon_tree: Tree, fs_tree: Tree) -> None:
    canon = canon_tree.people.get(xref)
    if not canon:
        print(f"no @{xref}@ in {canon_tree.ged.path.name}")
        return
    print(f"@{xref}@ {canon.label()}")
    print(f"  parents: {[p.label() for p in canon_tree.parents(xref)]}")
    print(f"  spouses: {[p.label() for p in canon_tree.spouses(xref)]}\n")
    rows = sorted(
        (
            (score_pair(canon, fs, canon_tree, fs_tree), fs)
            for fs in fs_tree.people.values()
        ),
        key=lambda row: -row[0].total,
    )[:6]
    for score, fs in rows:
        print(f"  {score.total:6.2f}  {fs.fsftid:10s} {fs.label()}")
        for reason in score.reasons:
            print(f"          - {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canonical", default=None)
    parser.add_argument("--dump", default=None, help="the exported GEDCOM to match against")
    parser.add_argument(
        "--live",
        action="store_true",
        help="match against the pedigree fetched by tools.fs.fetch instead of an "
        "exported GEDCOM; far more complete, and the only option if you have no export",
    )
    parser.add_argument("--pedigree", default=PEDIGREE, help="fetched pedigree JSON")
    parser.add_argument("--explain", metavar="XREF", help="show scoring for one person")
    args = parser.parse_args()

    canon_tree = Tree(args.canonical or tree_path())
    if args.live:
        from .fs.fetch import LiveTree

        path = Path(args.pedigree)
        if not path.exists():
            print(
                f"no hi ha cap pedigree a {path}. Baixa'l primer: "
                "python3 -m tools.fs.fetch",
                file=sys.stderr,
            )
            return 2
        fs_tree = LiveTree.from_json(json.loads(path.read_text(encoding="utf-8")))
    else:
        dump = Path(args.dump) if args.dump else fs_dump_path()
        if dump is None:
            print(
                "no hi ha cap exportació de FamilySearch per comparar. Posa-la al "
                "config.yaml («exportacio_familysearch:») o passa --live per fer "
                "servir les dades en viu.",
                file=sys.stderr,
            )
            return 2
        fs_tree = Tree(dump)
    print(canon_tree)
    print(fs_tree)

    if args.explain:
        explain(args.explain.strip("@"), canon_tree, fs_tree)
        return 0

    matches = match_trees(canon_tree, fs_tree)
    REPORTS.mkdir(exist_ok=True)
    write_report(matches, canon_tree, fs_tree, REPORTS / "match-report.md")
    n = write_proposals(matches, REPORTS / "fsftid-backfill.yaml")

    buckets = {b: sum(1 for m in matches if m.bucket == b) for b in ("confident", "review", "unmatched")}
    print(
        f"\nconfident {buckets['confident']}, review {buckets['review']}, "
        f"unmatched {buckets['unmatched']}"
    )
    print(f"wrote reports/match-report.md and reports/fsftid-backfill.yaml ({n} proposals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""What years the diocesan index actually covers, parish by parish.

This is the cheapest tool in the whole repository: it costs nothing and it stops
you spending one of your **fifteen daily queries** on a parish-year that was
never indexed. The table below comes from the archive's own coverage page,
transcribed once and re-checked against the live table on 30-07-2026.

The gaps are not decoration; they decide strategy. At Ontinyent, baptisms stop at
1744, restart in 1755 and stop again at 1780, while marriages are **complete from
1560 to 1900**. So for anybody born there before 1616 or between 1780 and 1900
the baptism cannot be looked up at all, and the way in is the **marriage** --
which is just as good for filiation, because a marriage fiche carries the parents
and the four grandparents of the person searched.

**These parishes are one Valencian branch's, and they are here as a working
example.** Replace them with yours: the archive publishes its own coverage table,
and transcribing it once is the cheapest hour you will spend on this. A parish
that is not in the table is reported as unknown rather than guessed at, which is
the behaviour you want -- see `covers()`.
"""

from __future__ import annotations

from dataclasses import dataclass

BAPTISM = "bateig"
MARRIAGE = "matrimoni"
DEATH = "defuncio"

# parish -> sacrament -> list of inclusive (from, to) year ranges.
COVERAGE: dict[str, dict[str, list[tuple[int, int]]]] = {
    "fontanars": {
        BAPTISM: [(1755, 1902)],
        MARRIAGE: [(1784, 1803), (1849, 1914)],
        DEATH: [(1851, 1901)],
    },
    "ontinyent": {
        BAPTISM: [(1616, 1744), (1755, 1780)],
        MARRIAGE: [(1560, 1900)],
        # Finer than the printed table said: the live coverage page on
        # 30-07-2026 splits this into 1722-1728 AND 1734-1744, so there is a
        # five-year hole (1729-1733) that the old figures hid.
        DEATH: [(1722, 1728), (1734, 1744), (1756, 1780), (1851, 1904)],
    },
    "agres": {
        BAPTISM: [(1564, 1915)],
        MARRIAGE: [(1565, 1925)],
        DEATH: [(1623, 1925)],
    },
    "albaida": {
        BAPTISM: [(1573, 1915)],
        MARRIAGE: [(1564, 1925)],
        DEATH: [(1872, 1925)],
    },
    "font de la figuera": {
        BAPTISM: [(1853, 1898)],
        MARRIAGE: [(1564, 1922)],
        DEATH: [(1579, 1919)],
    },
    "moixent": {
        BAPTISM: [(1567, 1575), (1892, 1901)],
        MARRIAGE: [],
        DEATH: [],
    },
    "bocairent": {
        BAPTISM: [(1725, 1834)],
        MARRIAGE: [(1725, 1870)],
        DEATH: [(1725, 1870)],
    },
}

# The archive will not serve anything more recent than this, by law.
EMBARGO_YEARS = {BAPTISM: 110, MARRIAGE: 100, DEATH: 100}


@dataclass(frozen=True)
class Verdict:
    """Whether a lookup is worth one of the fifteen."""

    possible: bool
    why: str

    def __bool__(self) -> bool:
        return self.possible


def covers(parish: str, sacrament: str, year: int | None, today_year: int = 2026) -> Verdict:
    """Is this parish-sacrament-year in the index at all?

    A `None` year is not an error and not a yes: plenty of the people in this
    tree have no date, and for them the honest answer is that the index cannot
    be aimed. Say so rather than returning a hopeful True.
    """
    key = _parish_key(parish)
    if key is None:
        return Verdict(False, f"«{parish}» no és una de les parròquies amb cobertura coneguda")
    ranges = COVERAGE[key].get(sacrament) or []
    if not ranges:
        return Verdict(False, f"l'índex no té cap {sacrament} de {key}")
    if year is None:
        spans = ", ".join(f"{a}-{b}" for a, b in ranges)
        return Verdict(False, f"sense any no es pot apuntar; {key} {sacrament} cobreix {spans}")

    embargo = today_year - EMBARGO_YEARS[sacrament]
    if year > embargo:
        return Verdict(False, f"{year} entra a l'embargament legal ({sacrament}: {EMBARGO_YEARS[sacrament]} anys)")

    for a, b in ranges:
        if a <= year <= b:
            return Verdict(True, f"{key} {sacrament} {a}-{b} inclou {year}")

    spans = ", ".join(f"{a}-{b}" for a, b in ranges)
    nearest = min(ranges, key=lambda r: min(abs(year - r[0]), abs(year - r[1])))
    hint = ""
    if year < nearest[0]:
        hint = f"; l'índex comença {nearest[0] - year} anys després"
    elif year > nearest[1]:
        hint = f"; s'acaba {year - nearest[1]} anys abans"
    return Verdict(False, f"{year} cau fora de {key} {sacrament} ({spans}){hint}")


def alternatives(parish: str, year: int | None) -> list[str]:
    """Which other sacraments at this parish DO cover the year.

    The point of the whole module: when the baptism is not there, say what is.
    """
    out = []
    for sacrament in (MARRIAGE, BAPTISM, DEATH):
        verdict = covers(parish, sacrament, year)
        if verdict:
            out.append(sacrament)
    return out


def _parish_key(parish: str) -> str | None:
    text = (parish or "").strip().lower()
    if not text:
        return None
    for key in COVERAGE:
        if key in text or text in key:
            return key
    return None

"""The four catalogue calls, and the field that decides if you can read a book.

    tree.php?parroquies=true      the 502 parishes, each with a prose summary
    tree.php?id=<id>              the children of one node
    udocs.php?id=<id>&items=&page= the books inside a series
    udoc.php?id=<id>              one book's fiche

The tree goes: parish -> SAGRAMENTS -> Baptismes -> "Llibres originals" -> books.
Every level is the same call; only the leaf list is different.

-----------------------------------------------------------------------------
TWO THINGS THAT WILL BITE YOU
-----------------------------------------------------------------------------

**`fills` is not the list of children, and it is not a count either.** The
parish list gives each node a `fills` array, and it looks exactly like the child
ids you want. It is not: verified on 30-07-2026, Adri (id 25) reports
`fills: [31]` while `tree.php?id=25` returns four children, and 31 is the id of
a *different parish* (Anglès). Whatever that field once meant, it is now
misleading in the one way that produces a plausible wrong answer -- you would
walk into another town's books and never notice. So `children()` always asks,
and `fills` is not read anywhere in this package.

**The ids in a fiche are not tree ids.** A fiche carries `_idserie: 100`, and
`udocs.php?id=100` returns an empty list, because `udocs.php` wants the *tree
node* id of the series (1203193 for that same series). They are separate
numberings and they overlap, so the wrong one gives you zero results rather than
an error -- which reads as "this series is empty" when it is not.

-----------------------------------------------------------------------------
AND THE ONE THAT MATTERS MOST
-----------------------------------------------------------------------------

**The catalogue describes books whose images it does not have.** The fiche exists
whether the book was digitised or not, so finding a fiche proves nothing about
being able to read it. `bucket: true` means the scans are in the bucket;
`condicions_acces` says what the archive permits. `Udoc.readable` is both, and
`Udoc.why_not()` says which failed -- because "physical consultation in the
reading room" and "not digitised" mean very different things for what you do
next: one is a trip to Girona, the other is a book that may not exist any more.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..normalize import fold
from .session import VIEWER, Session

# What `condicions_acces` says, and whether it lets you read from home. The
# archive writes these as prose, so this matches on the distinguishing word.
ACCESS_OPEN = ("consulta digital",)          # "Consulta digital al web"
ACCESS_PARTIAL = ("parcial",)                # "...parcial al web"
ACCESS_ONSITE = ("física", "fisica", "sala")   # "Consulta física a la sala"
ACCESS_CLOSED = ("fora de consulta",)


@dataclass
class Node:
    """One node of the classification tree: a parish, a group, a series."""

    id: str
    title: str
    has_documents: bool = False
    description: str = ""
    path: list = field(default_factory=list)
    indexed: bool = False

    @property
    def where(self) -> str:
        """The trail down to here, for a report line."""
        return " › ".join(step[1] for step in self.path if len(step) > 1)


@dataclass
class DocRef:
    """A book as the series listing gives it: enough to choose, not to judge.

    The listing carries no `bucket` and no access conditions, so you cannot tell
    from here whether a book is readable. That needs `fiche()`.
    """

    id: str
    title: str
    code: str = ""
    ref: str = ""


@dataclass
class Udoc:
    """One book's fiche: the whole answer to "can I read this, and from where?"."""

    id: str
    title: str
    code: str = ""
    fonds: str = ""
    group: str = ""
    series: str = ""
    year_from: int | None = None
    year_to: int | None = None
    access: str = ""
    digitised: bool = False
    s3_id: str = ""
    volume: str = ""
    language: str = ""
    contents: str = ""

    # -- the decision ---------------------------------------------------------

    @property
    def access_kind(self) -> str:
        """`open` | `partial` | `onsite` | `closed` | `unknown`."""
        text = fold(self.access)
        if not text:
            return "unknown"
        for needle in ACCESS_CLOSED:
            if needle in text:
                return "closed"
        for needle in ACCESS_PARTIAL:
            if needle in text:
                return "partial"
        for needle in ACCESS_ONSITE:
            if needle in text:
                return "onsite"
        for needle in ACCESS_OPEN:
            if needle in text:
                return "open"
        return "unknown"

    @property
    def readable(self) -> bool:
        """Can this be read from home right now?

        Both halves are required. A book can be digitised and still withheld
        (`Fora de consulta`), and the catalogue can promise digital consultation
        for a book with no images behind it.
        """
        return bool(self.digitised) and self.access_kind in {"open", "partial", "unknown"}

    def why_not(self) -> str:
        """Why not, in the words that decide what you do instead."""
        if self.readable:
            return ""
        if not self.digitised and self.access_kind == "onsite":
            return ("no digitalitzat i «consulta física a la sala»: això és una gestió "
                    "a fer a l'arxiu en persona, no una cosa que es puga desencallar des d'ací")
        if not self.digitised:
            return ("`bucket: false` — el catàleg el descriu però no en té imatges. "
                    "Que la fitxa existisca no vol dir que el llibre es puga mirar")
        if self.access_kind == "closed":
            return ("«fora de consulta»: digitalitzat però tancat. Val la pena preguntar "
                    "per què, que de vegades és un embargament amb data de caducitat")
        if self.access_kind == "onsite":
            return "digitalitzat però només consultable a la sala"
        return f"condicions d'accés: {self.access or '(no consta)'}"

    @property
    def viewer_url(self) -> str:
        return VIEWER.format(id=self.id)

    @property
    def years(self) -> str:
        if self.year_from and self.year_to:
            return f"{self.year_from}-{self.year_to}"
        return str(self.year_from or self.year_to or "?")

    def covers(self, year: int | None) -> bool:
        """Would this book contain that year? Unknown bounds never exclude."""
        if year is None:
            return False
        if self.year_from and year < self.year_from:
            return False
        if self.year_to and year > self.year_to:
            return False
        return bool(self.year_from or self.year_to)

    def line(self) -> str:
        mark = "" if self.readable else "~~"
        state = "en línia" if self.readable else self.why_not().split(":")[0]
        return (f"{mark}**{self.title}** ({self.years}){mark}\n"
                f"    id {self.id} · {self.code or 'sense codi'} · {state}")


# -- parsing -------------------------------------------------------------------

def _int_or_none(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _node(raw: dict) -> Node:
    return Node(
        id=str(raw.get("id") or ""),
        title=str(raw.get("titol") or ""),
        has_documents=bool(raw.get("udocs")),
        description=str(raw.get("descripcio") or ""),
        path=list(raw.get("path") or []),
        indexed=bool(raw.get("esta_indexat")),
    )


def parse_fiche(raw: dict) -> Udoc:
    """`{"udoc": {...}}` -> Udoc. Separate from fetching, so it is testable."""
    d = dict((raw or {}).get("udoc") or raw or {})
    return Udoc(
        id=str(d.get("_idudocsimple") or d.get("id") or ""),
        title=str(d.get("titol") or ""),
        code=str(d.get("codi") or ""),
        fonds=str(d.get("fons") or ""),
        group=str(d.get("grup") or ""),
        series=str(d.get("serie") or ""),
        year_from=_int_or_none(d.get("any_inici")),
        year_to=_int_or_none(d.get("any_fi")),
        access=str(d.get("condicions_acces") or ""),
        # `bucket` is the truth; `idamazon` is the folder the scans live in, and
        # it has matched the udoc id in everything seen so far -- but it is a
        # separate field, so it is read as one rather than assumed.
        digitised=bool(d.get("bucket")),
        s3_id=str(d.get("idamazon") or d.get("_idudocsimple") or ""),
        volume=str(d.get("volum_i_suport") or ""),
        language=str(d.get("llengua_i_escriptures") or ""),
        contents=str(d.get("abast_i_contingut") or ""),
    )


# -- the four calls ------------------------------------------------------------

def parishes(session: Session, refresh: bool = False) -> list[Node]:
    """Every parish in the archive, each with the prose summary of what survives.

    Half a megabyte and it never changes, so it is fetched once and then free.
    Read the summaries with suspicion: see `find_parish`.
    """
    data = session.get_json("tree.php?parroquies=true", "la llista de parròquies",
                            refresh=refresh)
    return [_node(x) for x in (data or [])]


def children(session: Session, node_id: str | int, refresh: bool = False) -> list[Node]:
    """The children of one node. Always asked, never inferred from `fills`."""
    data = session.get_json(f"tree.php?id={node_id}", f"els fills del node {node_id}",
                            refresh=refresh)
    return [_node(x) for x in (data or [])]


def documents(session: Session, node_id: str | int, items: int = 200,
              page: int = 1, refresh: bool = False) -> list[DocRef]:
    """The books inside a series. `node_id` is a TREE id, not a `_idserie`."""
    data = session.get_json(
        f"udocs.php?id={node_id}&items={items}&page={page}",
        f"els llibres de la sèrie {node_id}", refresh=refresh)
    return [
        DocRef(id=str(x.get("id") or ""), title=str(x.get("titol") or ""),
               code=str(x.get("codi") or ""), ref=str(x.get("ref") or ""))
        for x in ((data or {}).get("udocs") or [])
    ]


def fiche(session: Session, udoc_id: str | int, refresh: bool = False) -> Udoc | None:
    """One book's fiche. This is the call that answers "can I read it?"."""
    data = session.get_json(f"udoc.php?id={udoc_id}", f"la fitxa del llibre {udoc_id}",
                            refresh=refresh)
    if not data:
        return None
    return parse_fiche(data)


# -- finding your way ----------------------------------------------------------

def find_parish(session: Session, text: str, refresh: bool = False) -> list[Node]:
    """Parishes whose name contains `text`, accents and case ignored.

    Matching on the folded name and not the raw one is not cosmetic: the titles
    carry accents and the dedication ("Vilafant, parròquia de Sant Cebrià"), so
    a plain `in` on what you typed misses the town you are looking at.
    """
    needle = fold(text)
    if not needle:
        return []
    return [p for p in parishes(session, refresh=refresh) if needle in fold(p.title)]


def walk_series(session: Session, node_id: str | int, depth: int = 3) -> list[Node]:
    """Descend from a node to the levels that actually hold books.

    Deliberately breadth-first and depth-limited. This is the one place that
    could turn into a crawl of the whole archive, so it does not recurse freely:
    you name a parish, you get its series, and that is a handful of calls.
    """
    frontier = [(str(node_id), 0)]
    found: list[Node] = []
    seen = {str(node_id)}
    while frontier:
        current, level = frontier.pop(0)
        if level >= depth:
            continue
        for child in children(session, current):
            if child.id in seen:
                continue
            seen.add(child.id)
            found.append(child)
            frontier.append((child.id, level + 1))
    return found

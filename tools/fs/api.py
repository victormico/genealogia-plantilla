"""Typed wrappers over the FamilySearch platform endpoints we use.

Every call goes through Session.get, so every call is throttle-governed and
cached. Functions return plain parsed GEDCOM X JSON; the flattening into
something comparable with our GEDCOM lives in tools/match.py and
tools/research.py, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .session import Session

RECORDS_COLLECTION = "https://familysearch.org/platform/collections/records"

# The matches and search endpoints answer in GEDCOM X Atom, not plain GEDCOM X.
# Asking for the wrong one gets a bare 406 with no explanation.
ATOM = "application/x-gedcomx-atom+json"


@dataclass
class Api:
    fs: Session

    # -- tree -------------------------------------------------------------

    def person(self, pid: str) -> dict | None:
        """Full tree person: names, facts, sources summary."""
        return self.fs.get(f"/platform/tree/persons/{pid}")

    def persons(self, pids: list[str]) -> dict | None:
        """Up to 200 persons in one request. Cheapest way to read many people."""
        if len(pids) > 200:
            raise ValueError("the persons endpoint takes at most 200 pids")
        return self.fs.get("/platform/tree/persons", {"pids": ",".join(pids)})

    def ancestry(self, pid: str, generations: int = 8, details: bool = True) -> dict | None:
        """Ancestors of pid. 8 generations is the documented maximum per call."""
        params: dict[str, str | int] = {
            "person": pid,
            "generations": min(generations, 8),
        }
        if details:
            params["personDetails"] = "true"
            params["marriageDetails"] = "true"
        return self.fs.get("/platform/tree/ancestry", params)

    def descendancy(self, pid: str, generations: int = 2) -> dict | None:
        """Descendants of pid. 4 generations is the documented maximum."""
        return self.fs.get(
            "/platform/tree/descendancy",
            {"person": pid, "generations": min(generations, 4), "personDetails": "true"},
        )

    def parents(self, pid: str) -> dict | None:
        return self.fs.get(f"/platform/tree/persons/{pid}/parents")

    def children(self, pid: str) -> dict | None:
        return self.fs.get(f"/platform/tree/persons/{pid}/children")

    def spouses(self, pid: str) -> dict | None:
        return self.fs.get(f"/platform/tree/persons/{pid}/spouses")

    def changes(self, pid: str) -> dict | None:
        """Change history of a tree person, with who made each edit."""
        return self.fs.get(f"/platform/tree/persons/{pid}/changes", accept=ATOM)

    def contributors(self, pid: str) -> dict[str, str]:
        """Who has edited this person: {contributor id: name}.

        The point is to tell apart what the user entered himself from what a
        stranger did. FamilySearch is a shared tree, so a relationship somebody
        else added is a claim; one the user added is his own research, already
        cross-checked against relatives and registers.
        """
        data = self.changes(pid)
        out: dict[str, str] = {}
        for entry in (data or {}).get("entries") or ():
            for who in entry.get("contributors") or ():
                cid = who.get("resourceId") or (who.get("uri") or "").rsplit("/", 1)[-1]
                if cid:
                    out[cid] = who.get("name") or cid
        return out

    def edited_by_user(self, pid: str) -> bool:
        """Is the logged-in user among this person's editors?"""
        me = self.fs.tree_user_id
        return bool(me) and me in self.contributors(pid)

    def sources(self, pid: str) -> dict | None:
        """Source descriptions attached to a tree person, with their ARK URLs."""
        return self.fs.get(f"/platform/tree/persons/{pid}/sources")

    # -- matches ----------------------------------------------------------

    def duplicates(self, pid: str) -> dict | None:
        """Possible duplicates in the tree. No `collection` param, so ungated."""
        return self.fs.get(f"/platform/tree/persons/{pid}/matches", accept=ATOM)

    def record_hints(self, pid: str) -> dict | None:
        """FamilySearch's own record suggestions for a person.

        The `collection` parameter is restricted to certified applications in
        production, so this may return None. Callers must cope with that.
        """
        return self.fs.get(
            f"/platform/tree/persons/{pid}/matches",
            {"collection": RECORDS_COLLECTION},
            accept=ATOM,
        )

    # -- search -----------------------------------------------------------

    def tree_search(self, count: int = 20, offset: int = 0, **terms: str) -> dict | None:
        """Search the shared tree. Keys use underscores: given_name -> q.givenName.

        Rejects single-term searches unless the term is surname.
        """
        params = _search_params(terms)
        params.update({"count": min(count, 100), "offset": min(offset, 4999)})
        return self.fs.get("/platform/tree/search", params, accept=ATOM)

    def records_search(self, count: int = 20, offset: int = 0, **terms: str) -> dict | None:
        """Search the Historical Records archive (baptisms, marriages, burials).

        Place terms are not exact by default: FamilySearch expands them three
        jurisdiction levels down, so `birth_like_place="Ontinyent, València,
        Espanya"` also sweeps the surrounding province.
        """
        params = _search_params(terms)
        params.update({"count": min(count, 100), "offset": min(offset, 4999)})
        return self.fs.get("/platform/records/personas", params, accept=ATOM)

    # -- authorities ------------------------------------------------------

    def place_search(self, text: str, count: int = 10) -> dict | None:
        """Resolve a place name to FamilySearch's place authority."""
        return self.fs.get(
            "/platform/places/search",
            {"q": f'name:"{text}"', "count": count},
            accept="application/json",
        )


def _search_params(terms: dict[str, str]) -> dict[str, str]:
    """given_name -> q.givenName, f_collection_id -> f.collectionId, etc."""
    out: dict[str, str] = {}
    for key, value in terms.items():
        if value in (None, ""):
            continue
        prefix, _, rest = key.partition("_")
        if prefix in ("f", "c") and rest:
            key, category = rest, prefix
        else:
            category = "q"
        head, *tail = key.split("_")
        camel = head + "".join(w.capitalize() for w in tail)
        out[f"{category}.{camel}"] = str(value)
    return out

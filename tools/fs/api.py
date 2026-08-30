"""Typed wrappers over the FamilySearch platform endpoints we use.

Every call goes through Session.get, so every call is throttle-governed and
cached. Functions return plain parsed GEDCOM X JSON; the flattening into
something comparable with our GEDCOM lives in tools/match.py and
tools/research.py, not here.
"""

from __future__ import annotations

import re
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

    def citations(self, pid: str) -> list[dict]:
        """The documents FamilySearch cites for this person, flattened.

        Same shape of helper as `contributors`: the raw endpoint answers GEDCOM X,
        and what the rest of the code wants is a short list it can print and
        compare. Each entry carries the collection it comes from, the citation
        text, the people the citation names, and the ARK -- which is the part
        that matters, because two people attached to the *same* ARK are two
        people FamilySearch says one document covers.

        Why this exists: the proposals used to say who *typed* a relationship in
        (`contributors`) but never what document backed it. Issue #70 of the
        family tree was a whole afternoon of reading a GEDCOM by hand to find
        that the proposed father and the target shared one baptism record from
        1786 -- a fact this endpoint had all along and nobody asked for.

        Returns [] rather than raising when the person has no sources, when the
        endpoint 403s, or when the response has a shape we do not recognise:
        this is corroboration, and losing it must never stop a run.
        """
        return _citations(self.sources(pid))

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


# GEDCOM X fact types as they arrive on a source reference's tags, in the words
# the reports use. Anything not listed comes through lowercased and untranslated
# rather than dropped: an unknown tag is still information.
_FACTS = {
    "Birth": "naixement",
    "Christening": "bateig",
    "Baptism": "bateig",
    "Marriage": "matrimoni",
    "Death": "defunció",
    "Burial": "soterrament",
    "Residence": "residència",
    "Census": "padró",
    "Name": "nom",
    "Gender": "sexe",
    "Couple": "parella",
    "ParentChild": "filiació",
}


def _citations(data: dict | None) -> list[dict]:
    """Flatten a `/sources` response into one dict per attached document.

    Written to survive a payload it does not recognise. FamilySearch answers
    GEDCOM X, which leaves several of these fields optional and offers more than
    one place to put the ARK, and this runs unattended in a cron: an extraction
    that raised on a missing key would turn a nightly research run red over a
    person whose sources happen to be untitled.
    """
    if not isinstance(data, dict):
        return []

    described = {
        str(desc["id"]): desc
        for desc in data.get("sourceDescriptions") or ()
        if isinstance(desc, dict) and desc.get("id")
    }

    # `persons[].sources[]` is the attached list, in FamilySearch's own order,
    # and it is also what tells an attached document apart from the collection
    # description that rides along in the same payload. When it is absent --
    # some responses carry only the descriptions -- take them all rather than
    # return nothing.
    refs = [
        ref
        for person in data.get("persons") or ()
        for ref in (person or {}).get("sources") or ()
        if isinstance(ref, dict)
    ]
    pairs = (
        [(described.get(_description_id(ref)), ref) for ref in refs]
        if refs
        else [(desc, None) for desc in described.values()]
    )

    out: list[dict] = []
    seen: set[str] = set()
    for desc, ref in pairs:
        if not isinstance(desc, dict):
            continue
        cite = _one_citation(desc, ref)
        # The ARK is the identity of a document; two people can hold the same
        # one, but one person holding it twice is the same attachment twice.
        key = cite.get("url") or cite.get("title") or ""
        if not cite or (key and key in seen):
            continue
        seen.add(key)
        out.append(cite)
    return out


def _description_id(ref: dict) -> str:
    """`descriptionId: "SD-1"` or `description: "#SD-1"` -- both are in the wild."""
    ident = ref.get("descriptionId")
    if ident:
        return str(ident)
    return str(ref.get("description") or "").lstrip("#").rsplit("/", 1)[-1]


def _one_citation(desc: dict, ref: dict | None) -> dict:
    title = _first_value(desc.get("titles"))
    text = _first_value(desc.get("citations"))
    entry = {
        "title": title,
        "collection": _quoted(title) or _quoted(text),
        "text": text,
        "url": _ark(desc),
        "document": _document_ark(text),
        "names": _named(text),
        "about": _facts(ref),
    }
    return {k: v for k, v in entry.items() if v}


def citation_key(cite: dict) -> str:
    """What makes two citations the same document.

    NOT `url`. FamilySearch's `about` is the ARK of *this person's entry* in a
    record, so father and son on one baptism carry two different ones -- checked
    against the live API, the son G3CB-9ZT and the father LB8Z-YC4 share exactly
    zero `about` ARKs while sharing five documents. The ARK that identifies the
    document itself is the one quoted inside the citation text, and that is the
    one two people hold in common.
    """
    return cite.get("document") or cite.get("url") or cite.get("title") or ""


def _first_value(items: object) -> str:
    """titles/citations are lists of {"value": ...}; take the first real one."""
    for item in items or ():
        value = (item or {}).get("value") if isinstance(item, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _ark(desc: dict) -> str:
    """The record's own URL, from whichever of the three places carries it."""
    for candidate in (
        desc.get("about"),
        *(
            value
            for values in (desc.get("identifiers") or {}).values()
            for value in (values if isinstance(values, list) else [values])
        ),
        ((desc.get("links") or {}).get("self") or {}).get("href"),
    ):
        if isinstance(candidate, str) and "ark:" in candidate:
            # Same normalisation `search_records` does, so a URL from here and
            # one from a record search compare equal.
            return candidate.replace(
                "https://familysearch.org/ark:", "https://www.familysearch.org/ark:"
            )
    return ""


def _document_ark(text: str) -> str:
    """The record's own ARK, which FamilySearch quotes inside every citation.

    `"España, ...", FamilySearch (https://www.familysearch.org/ark:/61903/1:1:NSB1-J6P
    : Sat Aug 31 07:56:01 UTC 2024), Entry for Antonio Baliente and Juan
    Baliente, 22 Apr 1786.` -- the ARK in the middle is the document, and it is
    the same string on everyone attached to it.
    """
    match = re.search(r"ark:/\d+/[A-Za-z0-9:.\-]+", text or "")
    return match.group(0).rstrip(".:") if match else ""


def _quoted(text: str) -> str:
    """The collection name, which FamilySearch always puts in double quotes."""
    match = re.search(r'"([^"]{4,})"', text or "")
    return match.group(1).strip() if match else ""


def _named(text: str) -> list[str]:
    """Who the citation says the document is about.

    This is the line a human actually reads -- «Entry for Antonio Baliente and
    Juan Baliente, 22 Apr 1786» names a father and a son in one breath. It is
    best-effort parsing of a sentence, so it returns [] rather than a guess when
    the citation is not phrased the usual way; the ARK does the reliable work.
    """
    match = re.search(r"[Ee]ntry for\s+(.+)", text or "")
    if not match:
        return []
    kept: list[str] = []
    for chunk in match.group(1).rstrip(". ").split(", "):
        if chunk[:1].isdigit():  # the date that closes every citation
            break
        kept.append(chunk)
    names = [n.strip() for n in re.split(r"\s+and\s+|\s+y\s+", ", ".join(kept)) if n.strip()]
    return names[:6]


def _facts(ref: dict | None) -> list[str]:
    """What the document was attached as: bateig, matrimoni, defunció..."""
    out = {
        _FACTS.get(name, name.lower())
        for tag in (ref or {}).get("tags") or ()
        if (name := str((tag or {}).get("resource") or "").rsplit("/", 1)[-1])
    }
    return sorted(out)

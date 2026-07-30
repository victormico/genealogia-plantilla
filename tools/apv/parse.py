"""Turn an index results page into fiche records, and a fiche into a `.md`.

Two shapes come out of this archive and they are not the same thing:

  * the **results list** (`llistats.php`), one row per hit, with the sacrament
    reference and little else. This is what tells you whether the person is
    there at all.
  * the **fiche** (the detail table, and what the existing `.md` files in
    `Fonts/Arxiu Parroquial València/` transcribe), which carries the parents,
    the four grandparents, the officiant and the book/folio/entry.

The parser is deliberately forgiving about the HTML and strict about the fields:
the archive's markup is hand-rolled PHP with inconsistent tags, but the field
labels are stable. It matches on the labels.

Nothing here fetches. Feed it `session.get(...)` output, or a page you saved
from the browser -- both work, which is the point.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

SACRAMENTS = {"1": "Bateig", "2": "Confirmació", "4": "Matrimoni",
              "5": "Defunció", "6": "Matrícula Parroquial"}

# The eight kinship rows a fiche carries, in the archive's own order.
KIN_ORDER = ["Interessat/da", "Cònjuge", "Pare", "Mare",
             "Avi Patern", "Àvia paterna", "Avi Matern", "Àvia Materna"]

# Role labels are matched by STEM, because the archive writes them with gender
# suffixes -- «Interessat/da», «Interesado/a» -- and an exact-key lookup silently
# drops the single most important row of the fiche: the person themselves.
KIN_STEMS = (
    ("interessat", "Interessat/da"), ("interesado", "Interessat/da"),
    ("conjuge", "Cònjuge"), ("conyuge", "Cònjuge"),
    ("avi patern", "Avi Patern"), ("abuelo paterno", "Avi Patern"),
    ("avia paterna", "Àvia paterna"), ("abuela paterna", "Àvia paterna"),
    ("avi matern", "Avi Matern"), ("abuelo materno", "Avi Matern"),
    ("avia materna", "Àvia Materna"), ("abuela materna", "Àvia Materna"),
    ("pare", "Pare"), ("padre", "Pare"),
    ("mare", "Mare"), ("madre", "Mare"),
)


def kin_role(label: str) -> str | None:
    """Which kinship row this is, or None. Longest stem first so «avi patern»
    is not swallowed by a shorter match."""
    folded = _fold(label)
    if not folded:
        return None
    for stem, role in sorted(KIN_STEMS, key=lambda p: -len(p[0])):
        if folded.startswith(stem):
            return role
    return None

# Labels as the LIVE site writes them, which is Valencian and not always what
# the older printed fiches said: «Data Naiximent», not «Data Naixement»; «Còdic»,
# not «Codi». Both spellings are accepted so old saved pages still parse.
FIELD_LABELS = {
    "sagrament": "sacrament", "identificador": "identificador",
    "llibre": "book", "foli": "folio", "apunt": "entry", "sexe": "sex",
    "subcon": "subcon",
    "data naiximent": "birth_date", "data naixement": "birth_date",
    "data sagrament": "sacrament_date",
    "lloc sagrament": "sacrament_place", "oficiant": "officiant",
    "professio": "profession", "professio pare": "father_profession",
    "professio del pare": "father_profession",
    "domicili": "address",
    "inscrit en la parroquia": "registered_in", "inscrit en": "registered_in",
    "codic": "parish_code", "codi parroquia": "parish_code",
    "codic parroquia": "parish_code",
    "diocesi": "diocese", "diocesis de valencia": "diocese",
    "causa mort": "cause_of_death", "causa de la seua mort": "cause_of_death",
    "notes / observacions": "notes", "notes": "notes",
    "observacions": "notes",
}


@dataclass
class Kin:
    role: str
    given: str = ""
    surname1: str = ""
    surname2: str = ""
    birthplace: str = ""

    def full(self) -> str:
        return " ".join(p for p in (self.given, self.surname1, self.surname2) if p).strip()


@dataclass
class Fiche:
    """One sacramental entry as the index holds it."""

    fields: dict = field(default_factory=dict)
    kin: list = field(default_factory=list)

    # -- convenience ------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default) or default

    def sacrament_name(self) -> str:
        raw = self.get("sacrament")
        return SACRAMENTS.get(raw.strip(), raw)

    def person(self) -> Kin | None:
        return next((k for k in self.kin if k.role == "Interessat/da"), None)

    def reference(self) -> str:
        bits = [self.get("book"), self.get("folio"), self.get("entry")]
        return " · ".join(b for b in bits if b)

    def is_empty(self) -> bool:
        return not self.kin and not self.get("identificador")


def _text(fragment: str) -> str:
    """Strip tags and normalise whitespace, keeping the accents intact."""
    without = re.sub(r"<[^>]+>", "\n", fragment or "")
    return re.sub(r"[ \t\xa0]+", " ", html.unescape(without)).strip()


def _cells(row_html: str) -> list[str]:
    return [_text(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.S | re.I)]


# The live site puts the reference inside a single cell as
#   <small>IDENTIFICADOR</small><br><b>2289144</b>
# not as a label row followed by a value row. Reading it positionally gave
# «Sagrament = Identificador», which is how the first version of this parser
# lost the book, folio and entry -- the very fields you need to cite anything.
INLINE_PAIR = re.compile(
    r"<small[^>]*>(?P<label>.*?)</small>\s*(?:<br\s*/?>)?\s*<b[^>]*>(?P<value>.*?)</b>",
    re.S | re.I,
)
# And the extra block writes them as <div><b>Label:</b> value</div> -- sometimes
# WITH a colon («Professió Pare:») and sometimes without («Data Naiximent»), so
# the colon is optional. Matching loosely is safe here because only labels that
# appear in FIELD_LABELS are ever accepted, so stray bold text is discarded.
BOLD_PAIR = re.compile(
    r"<b[^>]*>(?P<label>[^<]{2,40}?):?\s*</b>\s*(?P<value>[^<]*)", re.S | re.I
)


def _harvest_pairs(fragment: str, fiche: Fiche) -> None:
    """Pull every label/value pair written inline, in either house style."""
    for pattern in (INLINE_PAIR, BOLD_PAIR):
        for m in pattern.finditer(fragment or ""):
            key = FIELD_LABELS.get(_fold(_text(m.group("label"))))
            value = _text(m.group("value"))
            if key and value and value != "...":
                fiche.fields.setdefault(key, value)


def parse_fiche(page: str) -> Fiche:
    """Read one detail table. Matches on labels, never on cell positions."""
    fiche = Fiche()
    # Inline pairs first: they are unambiguous and carry the reference.
    _harvest_pairs(page, fiche)

    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page or "", re.S | re.I)

    for row in rows:
        cells = [c for c in _cells(row)]
        if len(cells) < 2:
            continue

        # A kinship row: first cell is a role, then given / surname1 / surname2 / place.
        role = kin_role(cells[0])
        if role:
            values = cells[1:] + [""] * 4
            fiche.kin.append(Kin(
                role=role,
                given=values[0], surname1=values[1],
                surname2=values[2], birthplace=values[3],
            ))
            continue

        # A header row -- every cell is itself a field label -- must NOT be read as
        # label/value pairs, or «Sagrament» gets the value «Identificador» and
        # «Llibre» gets «Foli». The real values are on the row below it.
        labelled = [c for c in cells if c.strip()]
        if len(labelled) >= 3 and all(_fold(c) in FIELD_LABELS for c in labelled):
            continue

        # Otherwise: pairs of label/value across the row.
        for i in range(0, len(cells) - 1, 2):
            key = FIELD_LABELS.get(_fold(cells[i]))
            if key and cells[i + 1] not in ("", "..."):
                fiche.fields.setdefault(key, cells[i + 1])

    # Older saved pages (and the pre-2026 interface) put the reference as a
    # label row followed by a value row. Only used if the inline sweep found
    # nothing, so it can never overwrite the live layout.
    if not fiche.get("identificador"):
        header = re.search(
            r"Sagrament.*?Identificador.*?Llibre.*?Foli.*?Apunt.*?Sexe",
            page or "", re.S | re.I)
        if header:
            after = page[header.end():]
            next_row = re.search(r"<tr[^>]*>(.*?)</tr>", after, re.S | re.I)
            values = _cells(next_row.group(1)) if next_row else []
            for key, value in zip(
                ("sacrament", "identificador", "book", "folio", "entry", "sex"), values
            ):
                if value:
                    fiche.fields.setdefault(key, value)
    return fiche


def parse_results(page: str) -> list[dict]:
    """Read a `llistats.php` hit list. Returns one dict per row.

    Also surfaces the archive's own quota line if it is on the page, because
    that is the authoritative count and worth seeing in the output.
    """
    hits: list[dict] = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page or "", re.S | re.I):
        cells = _cells(row)
        if len(cells) < 2:
            continue
        joined = " ".join(cells)
        ref = re.search(r"\b([A-Z]{1,3}-?\d{0,3})\s*\((\d{4})[_\-](\d{4})\)\s*"
                        r"(?:Folio|Foli)\s*(\d+\w?)", joined, re.I)
        if ref:
            hits.append({
                "book": ref.group(1), "from": ref.group(2), "to": ref.group(3),
                "folio": ref.group(4), "row": joined,
                "registro": (re.search(r"Registro\s*num\.?\s*(\d+)", joined, re.I) or
                             [None, ""])[1] if re.search(r"Registro", joined, re.I) else "",
            })
    return hits


def quota_line(page: str) -> str:
    """The archive's own «ya has realizado N de 15», if present."""
    found = re.search(r"(m[áa]ximo de.{0,120}?)(?:</|\n)", _text(page or ""), re.S | re.I)
    return found.group(1).strip() if found else ""


def to_markdown(fiche: Fiche, title: str, source_note: str = "") -> str:
    """Render a fiche in the shape the other files in this archive folder use."""
    person = fiche.person()
    who = person.full() if person else title
    lines = [f"# {who} — {fiche.sacrament_name().lower()}", ""]
    lines += [
        "**Font**: Arxiu Parroquial de València, índex del Servici Diocesà d'Arxius",
        "Parroquials. **És la transcripció de l'índex, no del manuscrit original.**",
    ]
    if source_note:
        lines += ["", source_note]
    lines += ["", "| | |", "| --- | --- |"]
    for label, key in (("Sagrament", "sacrament"), ("Identificador", "identificador"),
                       ("Llibre", "book"), ("Foli", "folio"), ("Apunt", "entry"),
                       ("Sexe", "sex"), ("Codi parròquia", "parish_code")):
        value = fiche.get(key)
        if value:
            shown = fiche.sacrament_name() if key == "sacrament" else value
            lines.append(f"| {label} | {shown} |")
    lines.append("")
    for label, key in (("Data de naixement", "birth_date"),
                       ("Data del sagrament", "sacrament_date"),
                       ("Lloc", "sacrament_place"), ("Oficiant", "officiant"),
                       ("Inscrit a", "registered_in"), ("Professió", "profession"),
                       ("Notes", "notes")):
        value = fiche.get(key)
        if value:
            lines.append(f"**{label}**: {value}")
    if fiche.kin:
        lines += ["", "## Familiars", "", "| Vincle | Nom | Lloc de naixement |",
                  "| --- | --- | --- |"]
        for role in KIN_ORDER:
            for k in (x for x in fiche.kin if x.role == role):
                if k.full():
                    lines.append(f"| {k.role} | {k.full()} | {k.birthplace} |")
    lines += ["", "> **Els llocs dels avis no són prova.** La columna «Lloc Naiximent» de",
              "> l'índex repeteix la parròquia de l'apunt quan no en té constància; els noms",
              "> sí que valen. Vegeu la lliçó del 1847 al LLEGIU-ME d'aquesta carpeta.", ""]
    return "\n".join(lines)


def _fold(text: str) -> str:
    import unicodedata

    stripped = "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"[^a-z/ ]+", "", stripped).strip()

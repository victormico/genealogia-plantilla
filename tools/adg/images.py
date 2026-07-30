"""The image bucket: the URL pattern, where a book ends, and the download.

    https://arxiu-diocesa.s3.eu-west-3.amazonaws.com/<id>/<id>_<page>_<res>.jpg
                                                     res: l low · m medium · h high

-----------------------------------------------------------------------------
THE PAGE NUMBER, WHICH IS THE WHOLE TRAP
-----------------------------------------------------------------------------

**Zero-padded to two digits, and no further.** Verified against the bucket on
30-07-2026:

    page 7   -> `_07_`     `_7_` answers 403
    page 80  -> `_80_`
    page 100 -> `_100_`    `_0100_` answers 403

So it is `%02d`: pad to two, then let it grow. Both mistakes look identical from
outside -- a 403 -- and a 403 is also what the end of the book looks like, which
is how you conclude a book "does not exist" when what you asked for was page 1
spelled wrong. That is why `page_segment` is a function with tests and not an
f-string at the call site.

**A missing page answers 403, not 404.** The bucket refuses to say whether a key
is absent, so past-the-end and never-existed are the same answer. Useful rather
than annoying: it makes the end of a book findable by bisection, which is what
`bisect_last_page` does with HEAD requests, for a few hundred bytes each.

-----------------------------------------------------------------------------
AND THE LIMIT THAT IS DELIBERATE
-----------------------------------------------------------------------------

`download_pages` refuses more than `MAX_PAGES_PER_RUN` at a time. The archive
permits copies for personal use and charges rights for republication, and the
difference between the two is exactly whether you take the eight pages that hold
your ancestor or the whole book. The cap is raisable by an argument, because
sometimes a certificate runs across a gathering -- but it has to be asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .session import BUCKET, Session

LOW, MEDIUM, HIGH = "l", "m", "h"
RESOLUTIONS = (LOW, MEDIUM, HIGH)

# `m` is legible for print and most hands; `h` is for difficult script.
DEFAULT_RESOLUTION = MEDIUM

MAX_PAGES_PER_RUN = 12

# No real book runs past this. It only bounds the doubling search below, so that
# a bucket behaving oddly cannot spin forever.
PAGE_CEILING = 2048


def page_segment(page: int) -> str:
    """The page as the bucket spells it: padded to two digits, then natural.

        >>> page_segment(7), page_segment(80), page_segment(100)
        ('07', '80', '100')
    """
    if page < 1:
        raise ValueError(f"les pàgines comencen a 1, no a {page}")
    return f"{page:02d}"


def image_url(book_id: str | int, page: int, resolution: str = DEFAULT_RESOLUTION) -> str:
    """The URL of one scan."""
    if resolution not in RESOLUTIONS:
        raise ValueError(
            f"la resolució és «{'», «'.join(RESOLUTIONS)}», no «{resolution}»")
    book = str(book_id)
    return f"{BUCKET}/{book}/{book}_{page_segment(page)}_{resolution}.jpg"


def page_exists(session: Session, book_id: str | int, page: int,
                resolution: str = DEFAULT_RESOLUTION) -> bool | None:
    """Is that page there? A cached HEAD."""
    return session.image_exists(image_url(book_id, page, resolution))


def bisect_last_page(session: Session, book_id: str | int,
                     resolution: str = DEFAULT_RESOLUTION,
                     ceiling: int = PAGE_CEILING) -> int | None:
    """How many pages the book has, found by asking for pages that are not there.

    Double until a page is missing, then binary search the boundary: about
    2·log2(n) HEAD requests, so roughly twenty for a two-hundred-page book, and
    they are cached, so asking twice is free.

    Returns None if page 1 itself is missing -- which means either the book is
    not digitised (check `catalog.Udoc.digitised` first, it is one call and it
    answers properly) or you have the wrong id.
    """
    first = page_exists(session, book_id, 1, resolution)
    if first is None:      # dry run
        return None
    if not first:
        return None

    known, unknown = 1, 2
    while unknown <= ceiling:
        if page_exists(session, book_id, unknown, resolution):
            known, unknown = unknown, unknown * 2
        else:
            break
    else:
        return known

    # known exists, unknown does not: the last page is in [known, unknown).
    low, high = known, unknown
    while high - low > 1:
        middle = (low + high) // 2
        if page_exists(session, book_id, middle, resolution):
            low = middle
        else:
            high = middle
    return low


@dataclass
class Downloaded:
    page: int
    path: Path
    size: int


def parse_pages(spec: str) -> list[int]:
    """`"3"`, `"3-7"`, `"3,9,11-13"` -> a sorted list of page numbers."""
    pages: set[int] = set()
    for chunk in str(spec).replace(" ", "").split(","):
        if not chunk:
            continue
        if "-" in chunk:
            start, _, end = chunk.partition("-")
            a, b = int(start), int(end)
            if a > b:
                raise ValueError(f"el rang «{chunk}» va cap enrere")
            pages.update(range(a, b + 1))
        else:
            pages.add(int(chunk))
    if any(p < 1 for p in pages):
        raise ValueError("les pàgines comencen a 1")
    return sorted(pages)


def download_pages(session: Session, book_id: str | int, pages: list[int],
                   out_dir: Path, resolution: str = DEFAULT_RESOLUTION,
                   max_pages: int = MAX_PAGES_PER_RUN) -> list[Downloaded]:
    """Save these pages, and refuse to save a whole book.

    Files land as `<id>_<page>_<res>.jpg`, which keeps the bucket's own naming so
    that a file on disk can always be traced back to its URL. An existing file is
    left alone rather than re-fetched.
    """
    if not pages:
        return []
    if len(pages) > max_pages:
        raise ValueError(
            f"{len(pages)} pàgines de cop, i el límit d'aquesta eina és {max_pages}. "
            "L'arxiu permet còpies per a ús personal i cobra drets per republicar, i "
            "la diferència entre les dues coses és justament aquesta. Baixa les "
            "pàgines que et fan falta; si de veres en calen més, puja el límit a mà "
            "amb --max-pagines i que siga una decisió teva."
        )

    if not getattr(session, "dry_run", False):
        out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Downloaded] = []
    for page in pages:
        url = image_url(book_id, page, resolution)
        target = out_dir / f"{book_id}_{page_segment(page)}_{resolution}.jpg"
        if target.exists():
            print(f"  ja el tens: {target.name}")
            saved.append(Downloaded(page, target, target.stat().st_size))
            continue
        body = session.fetch_image(url)
        if body is None:
            # In a dry run nothing was asked for, so saying "not there" would be
            # a lie about the archive rather than a report about the rehearsal.
            if not getattr(session, "dry_run", False):
                print(f"  pàgina {page}: no hi és (403) o no s'ha pogut baixar")
            continue
        target.write_bytes(body)
        print(f"  {target.name} — {len(body) / 1024:.0f} KB")
        saved.append(Downloaded(page, target, len(body)))
    return saved

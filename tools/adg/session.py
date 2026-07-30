"""Paced, cached HTTP against the diocesan catalogue and its image bucket.

Modelled on tools/apv/session.py, minus the quota: this archive publishes no
daily cap and no API terms. That is a reason for more care rather than less --
there is no published budget to stay inside, so the restraint has to come from
here.

-----------------------------------------------------------------------------
WHAT THIS FILE ENFORCES
-----------------------------------------------------------------------------

**Everything is cached forever.** The catalogue is a description of paper that
has not moved in centuries; a book's fiche today is its fiche next month. So a
report can be regenerated, and a tree walked again, at no cost to the archive.
Pass `refresh=True` to override for one call.

**One request at a time, with a gap between them.** No concurrency, ever. The
whole tool is one person looking things up.

**HEAD for probing, GET only to keep.** Finding where a book ends takes a dozen
requests (see images.bisect_last_page), and doing that with GETs would pull a
dozen full-resolution scans down to throw them away. HEAD asks the same question
for a few hundred bytes.

**It identifies itself.** `config.user_agent` puts the project name and, if you
filled it in, a contact address in the User-Agent. An archive that can see who
is making the requests can ask you to stop instead of blocking the range.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .. import config

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache" / "adg"

# The catalogue is JSON over PHP; the images are a public S3 bucket.
API = "https://arxiubisbatgirona.org/api"
BUCKET = "https://arxiu-diocesa.s3.eu-west-3.amazonaws.com"
VIEWER = "https://arxiubisbatgirona.org/visor2.php?id={id}"

MIN_SECONDS_BETWEEN = 1.5

USER_AGENT = config.user_agent("adg")


class ArchiveDown(RuntimeError):
    """The catalogue answered something other than JSON, or nothing at all."""


class Session:
    """One request at a time, cached forever.

    `dry_run` prints what it would ask for and returns nothing, which is how
    every command in browse.py can be rehearsed before it touches the network.
    """

    def __init__(self, cache_dir: Path | None = None, dry_run: bool = False):
        self.dry_run = dry_run
        self.requests_made = 0
        self.cache_hits = 0
        self.bytes_fetched = 0
        self._last_request = 0.0
        try:
            import diskcache

            self.cache = diskcache.Cache(str(cache_dir or CACHE_DIR))
        except ImportError:
            # Worth saying out loud rather than degrading quietly: without the
            # cache every re-run costs the archive the full set of requests
            # again, and "a repeat is free" is the promise this tool is built on.
            self.cache = None
            print("  AVÍS: sense `diskcache` no hi ha memòria cau i cada execució "
                  "torna a demanar-ho tot a l'arxiu. Instal·la-la amb "
                  "`pip install -r requirements.txt`.")
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": USER_AGENT,
            "Accept-Language": "ca,es;q=0.9",
        })

    # -- pacing ---------------------------------------------------------------

    def _wait(self) -> None:
        gap = time.monotonic() - self._last_request
        if self._last_request and gap < MIN_SECONDS_BETWEEN:
            time.sleep(MIN_SECONDS_BETWEEN - gap)

    # -- the catalogue --------------------------------------------------------

    def get_json(self, path: str, why: str = "", refresh: bool = False):
        """One catalogue call. `path` is like `tree.php?id=500`.

        Returns the decoded JSON, or None in a dry run.
        """
        url = f"{API}/{path}"
        key = f"json:{url}"
        if self.cache is not None and not refresh:
            hit = self.cache.get(key, default=None)
            if hit is not None:
                self.cache_hits += 1
                return json.loads(hit)

        if self.dry_run:
            print(f"  [assaig en sec] no es demana res: {why or url}")
            return None

        self._wait()
        response = self.http.get(url, timeout=45)
        self._last_request = time.monotonic()
        self.requests_made += 1
        self.bytes_fetched += len(response.content or b"")

        if response.status_code != 200:
            raise ArchiveDown(
                f"HTTP {response.status_code} a {url}. El catàleg no ha respost; "
                "no és res que puguis arreglar tu, torna-hi més tard."
            )

        # The endpoints declare text/html and serve JSON. Trust the body.
        try:
            data = response.json()
        except ValueError as exc:
            raise ArchiveDown(
                f"{url} no ha tornat JSON sinó {len(response.content)} bytes de una "
                "altra cosa. Sol voler dir que l'endpoint ha canviat de nom: obri la "
                "URL al navegador i mira què serveix ara."
            ) from exc

        if self.cache is not None:
            self.cache.set(key, json.dumps(data, ensure_ascii=False))
        return data

    # -- the image bucket -----------------------------------------------------

    def image_exists(self, url: str, refresh: bool = False) -> bool | None:
        """Does this scan exist? A HEAD, cached, because bisection repeats them.

        A missing page answers 403, not 404 -- the bucket denies listing rather
        than admitting the key is absent -- so 403 is the normal "past the end"
        answer here and not an error. See images.bisect_last_page.
        """
        key = f"head:{url}"
        if self.cache is not None and not refresh:
            hit = self.cache.get(key, default=None)
            if hit is not None:
                self.cache_hits += 1
                return bool(hit)

        if self.dry_run:
            print(f"  [assaig en sec] no es comprova: {url}")
            return None

        self._wait()
        response = self.http.head(url, timeout=30)
        self._last_request = time.monotonic()
        self.requests_made += 1
        found = response.status_code == 200

        if self.cache is not None:
            self.cache.set(key, found)
        return found

    def fetch_image(self, url: str) -> bytes | None:
        """Download one scan. Not cached: it goes to a file you keep."""
        if self.dry_run:
            print(f"  [assaig en sec] no es baixa: {url}")
            return None

        self._wait()
        response = self.http.get(url, timeout=120)
        self._last_request = time.monotonic()
        self.requests_made += 1

        if response.status_code != 200:
            return None
        self.bytes_fetched += len(response.content or b"")
        return response.content

    def stats(self) -> str:
        mb = self.bytes_fetched / 1_048_576
        return (
            f"{self.requests_made} peticions, {self.cache_hits} de memòria cau, "
            f"{mb:.1f} MB baixats"
        )

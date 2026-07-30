"""Cached, quota-governed session against the diocesan index at Ontinyent.

Modelled on tools/fs/session.py, with the difference that matters here: this
archive rations by **queries per day**, not by server time, and it says so on
every page it serves.

-----------------------------------------------------------------------------
THE RULES THIS FILE ENFORCES, AND WHERE THEY COME FROM
-----------------------------------------------------------------------------

**Fifteen queries a day.** The archive prints it on the results page: «Debido a
los expolios que últimamente esta sufriendo esta base de datos, nos vemos
obligados a limitar el acceso a las consultas a un máximo de 15 diarias, de las
cuales ya has realizado 6». That is a hard ceiling here, not a hint:

  * the counter is kept **on disk**, keyed by date, so it survives restarts.
    A cap that resets when the process does is not a cap.
  * the page also states the archive's OWN running total, which we parse and
    treat as **authoritative** -- if the server says 9 and we thought 4, ours
    jumps to 9. Somebody was searching in a browser and those count too.
  * cache hits cost nothing and are not counted, which is why every response is
    cached forever. Re-running a report is free.

**What robots.txt actually says.** `User-agent: *` gets `Allow: /` plus
`Content-Signal: search=yes, ai-train=no, use=reference`. The `Disallow: /`
lines are Cloudflare's managed list of AI *training* crawlers -- ClaudeBot,
GPTBot, CCBot, Bytespider, Amazonbot, Google-Extended, Applebot-Extended,
meta-externalagent. Reading fifteen specific ancestors' baptism fiches is
`use=reference`, which the signal permits, and is not `ai-train`, which it
forbids. This tool therefore identifies itself honestly as a personal research
tool, not as any of those crawlers, and never enumerates the database.

**And the thing it will never do**: no crawling, no pagination sweeps, no
surname harvesting. One person, one lookup. If you find yourself wanting to
loop over a result set, stop -- that is the behaviour the archive is
complaining about.

Terms of use permit viewing, printing, copying and storing for personal use and
forbid commercial reproduction and republication. `Fonts/` is gitignored.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path

import requests

from .. import config

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache"
QUOTA_FILE = CACHE_DIR / "apv-quota.json"

DAILY_LIMIT = 15
MIN_SECONDS_BETWEEN = 6.0

# See the note in tools/fs/session.py: this comes from config.yaml.
USER_AGENT = config.user_agent("apv")

# «de las cuales ya has realizado 6» / «dont vous avez déjà effectué 6»
SERVER_COUNT = re.compile(
    r"(?:ya\s+has\s+realizado|d[ée]j[àa]\s+effectu[ée])\s*<?[^>]*>?\s*(\d+)", re.I
)
SERVER_LIMIT = re.compile(
    r"m[áa]ximo\s+de\s*<?[^>]*>?\s*(\d+)\s*diarias", re.I
)


class QuotaExhausted(RuntimeError):
    """The day's fifteen are gone. Not an error to retry -- come back tomorrow."""


class Challenged(RuntimeError):
    """Cloudflare wants a real browser, and that is the end of the script path.

    Confirmed on 30-07-2026: a plain GET to llistats.php answers HTTP 403 with
    `cf-mitigated: challenge` and a «Just a moment… Enable JavaScript and
    cookies to continue» interstitial (`cType: 'managed'`).

    Getting past that would mean impersonating a browser or driving a headless
    one to solve the challenge -- circumventing an access control the archive
    deliberately switched on. Not done here, and not to be added.

    What works instead, and is what the archive actually permits: open the URL
    in a real browser. tools.apv.verify prints every URL for exactly that, and
    tools/apv/parse.py reads the saved page back, so nothing downstream is lost.
    """


class Quota:
    """A daily counter that lives on disk, so it cannot be lost by restarting."""

    def __init__(self, path: Path = QUOTA_FILE, limit: int = DAILY_LIMIT):
        self.path = path
        self.limit = limit
        self._state = self._load()

    def _load(self) -> dict:
        today = date.today().isoformat()
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
                if state.get("day") == today:
                    return state
            except (ValueError, OSError):
                pass
        return {"day": today, "used": 0, "server_said": None, "log": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._state, ensure_ascii=False, indent=1), encoding="utf-8")

    @property
    def used(self) -> int:
        return int(self._state.get("used") or 0)

    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def check(self, n: int = 1) -> None:
        """Refuse before spending, not after."""
        if self.used + n > self.limit:
            raise QuotaExhausted(
                f"les {self.limit} consultes d'avui ({self._state['day']}) estan gastades "
                f"({self.used} fetes). L'arxiu les limita per dia i això no es força: "
                f"torna demà, o mira si el que busques ja és a la memòria cau."
            )

    def spend(self, what: str) -> None:
        self._state["used"] = self.used + 1
        self._state.setdefault("log", []).append({"what": what, "at": time.strftime("%H:%M:%S")})
        self._save()

    def reconcile(self, html: str) -> int | None:
        """Trust the archive's own counter over ours."""
        found = SERVER_COUNT.search(html or "")
        if not found:
            return None
        theirs = int(found.group(1))
        self._state["server_said"] = theirs
        if theirs > self.used:
            self._state["used"] = theirs
        limit = SERVER_LIMIT.search(html or "")
        if limit:
            self.limit = int(limit.group(1))
            self._state["limit"] = self.limit
        self._save()
        return theirs

    def summary(self) -> str:
        said = self._state.get("server_said")
        extra = f", l'arxiu deia {said}" if said is not None else ""
        return f"{self.used}/{self.limit} consultes avui ({self._state['day']}{extra})"


class Session:
    """One lookup at a time, cached forever, counted against the daily fifteen."""

    def __init__(self, cache_dir: Path | None = None, limit: int = DAILY_LIMIT,
                 dry_run: bool = False):
        self.quota = Quota(limit=limit)
        self.dry_run = dry_run
        self.requests_made = 0
        self.cache_hits = 0
        self._last_request = 0.0
        try:
            import diskcache

            self.cache = diskcache.Cache(str(cache_dir or CACHE_DIR / "apv"))
        except ImportError:
            self.cache = None
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ca,es;q=0.9",
        })

    def get(self, url: str, why: str = "", refresh: bool = False) -> str | None:
        """Fetch one search URL. Returns HTML, or None if it was refused.

        Cached responses cost nothing and do not touch the quota.
        """
        if self.cache is not None and not refresh:
            hit = self.cache.get(url, default=None)
            if hit is not None:
                self.cache_hits += 1
                return hit

        if self.dry_run:
            print(f"  [assaig en sec] no es demana res: {why or url}")
            return None

        self.quota.check()

        gap = time.monotonic() - self._last_request
        if self._last_request and gap < MIN_SECONDS_BETWEEN:
            time.sleep(MIN_SECONDS_BETWEEN - gap)

        response = self.http.get(url, timeout=45)
        self._last_request = time.monotonic()
        self.requests_made += 1

        if response.status_code != 200:
            # Deliberately NOT counted against the quota. A challenge or a 5xx
            # means the search never ran, so the archive's own counter did not
            # move either -- and the next successful response re-syncs us from
            # that counter anyway. Counting these would burn real lookups on
            # requests that returned no data.
            if response.status_code == 403 and "cf-mitigated" in {
                k.lower() for k in response.headers
            }:
                raise Challenged(
                    "Cloudflare ha posat un repte gestionat («Just a moment…», "
                    "cal JavaScript i galetes). La consulta NO s'ha fet i no es "
                    "compta. Aquest camí no es pot passar des d'un script sense "
                    "falsejar el client, i això no es fa: obri la URL al navegador."
                )
            print(f"  HTTP {response.status_code} — no comptada, no desada a la memòria cau")
            return None

        self.quota.spend(why or url)

        # The form is latin-1; requests will guess wrong on pages with no charset.
        response.encoding = response.encoding or "latin-1"
        html = response.text

        theirs = self.quota.reconcile(html)
        if theirs is not None and theirs >= self.quota.limit:
            print(f"  AVÍS: l'arxiu diu que ja portes {theirs}/{self.quota.limit} consultes avui.")

        if self.cache is not None:
            self.cache.set(url, html)
        return html

    def stats(self) -> str:
        return (
            f"{self.requests_made} peticions, {self.cache_hits} de memòria cau; "
            f"{self.quota.summary()}"
        )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT,
                        help=f"sostre diari de consultes (per defecte {DAILY_LIMIT}); "
                             "només serveix per BAIXAR-lo")
    parser.add_argument("--dry-run", action="store_true",
                        help="no demana res: només diu què demanaria")
    parser.add_argument("--quota", action="store_true",
                        help="diu quantes consultes queden avui i para")
    parser.add_argument("--record", metavar="QUÈ", action="append", default=[],
                        help="apunta una consulta feta A MÀ al navegador. El sostre "
                             "és de l'arxiu, no del nostre script: una cerca feta al "
                             "navegador el gasta igual, i si no s'apunta el comptador "
                             "menteix. Repetible.")


def build_session(args: argparse.Namespace) -> Session:
    limit = min(int(getattr(args, "limit", DAILY_LIMIT) or DAILY_LIMIT), DAILY_LIMIT)
    return Session(limit=limit, dry_run=bool(getattr(args, "dry_run", False)))

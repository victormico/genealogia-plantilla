"""Cached, quota-governed session against the diocesan index at Ontinyent.

Modelled on tools/fs/session.py, with the difference that matters here: this
archive rations by **queries per day**, not by server time, and it says so on
every page it serves.

-----------------------------------------------------------------------------
THE RULES THIS FILE ENFORCES, AND WHERE THEY COME FROM
-----------------------------------------------------------------------------

**There is no confirmed daily ceiling.** This file used to enforce fifteen
queries a day as a hard limit, sourced from a secondhand claim -- «Debido a
los expolios que últimamente esta sufriendo esta base de datos, nos vemos
obligados a limitar el acceso a las consultas a un máximo de 15 diarias, de las
cuales ya has realizado 6» -- that nobody had actually seen on the live site.
Checking the site directly found no such message: `SERVER_COUNT` and
`SERVER_LIMIT` below have never once matched a real page, and
`cache/apv-quota.json` keeps reading `"server_said": null`. A sentence quoted
secondhand became a constant in code, and then a "hard ceiling" in the docs,
without anybody checking the source.

So what is left, and why:

  * **`SOFT_DAILY` is a pace you choose, not a rule you are under.** Going past
    it warns and keeps working. It exists so that a loop cannot quietly make
    hundreds of requests, not because anybody confirmed a real number -- the
    default below is a reasonable starting point and yours to change.
  * **If the archive ever does state a limit, it wins and it is hard.**
    `reconcile()` parses both the running total and the ceiling off the page;
    the moment a real page declares one, `check()` starts refusing. The
    server's word beats ours in both directions.
  * the counter is kept **on disk**, keyed by date, so it survives restarts,
    and its `log` is the record of what was actually asked. That log is worth
    more than the cap ever was: it lets a search that came back empty be
    recognised later instead of proposed again.
  * cache hits cost nothing and are not counted, which is why every response is
    cached forever. Re-running a report is free.

**What robots.txt actually says.** `User-agent: *` gets `Allow: /` plus
`Content-Signal: search=yes, ai-train=no, use=reference`. The `Disallow: /`
lines are Cloudflare's managed list of AI *training* crawlers -- ClaudeBot,
GPTBot, CCBot, Bytespider, Amazonbot, Google-Extended, Applebot-Extended,
meta-externalagent. Reading a handful of specific ancestors' baptism fiches is
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

from ..config import ROOT
CACHE_DIR = ROOT / "cache"
QUOTA_FILE = CACHE_DIR / "apv-quota.json"

# Our own courtesy pace, not the archive's rule -- see the header. Passing it
# warns; only a limit the archive itself declares is ever enforced.
SOFT_DAILY = 40
DAILY_LIMIT = SOFT_DAILY  # kept for callers that still import the old name
MIN_SECONDS_BETWEEN = 6.0

# See the note in tools/fs/session.py: this comes from config.yaml.
USER_AGENT = config.user_agent("apv")

# «de las cuales ya has realizado 6» / «dont vous avez déjà effectué 6»
#
# Both numbers can arrive wrapped in markup -- «máximo de <b>15</b> diarias» --
# so each side of the digit has to tolerate a run of tags.
TAGS = r"(?:<[^>]*>\s*)*"
SERVER_COUNT = re.compile(
    r"(?:ya\s+has\s+realizado|d[ée]j[àa]\s+effectu[ée])\s*" + TAGS + r"(\d+)", re.I
)
SERVER_LIMIT = re.compile(
    r"m[áa]ximo\s+de\s*" + TAGS + r"(\d+)\s*" + TAGS + r"diarias", re.I
)


class QuotaExhausted(RuntimeError):
    """Today's pace is spent, and the archive itself declared it -- not us."""


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

    def __init__(self, path: Path | None = None, limit: int = SOFT_DAILY,
                 hard: bool = False):
        # Resolved here rather than bound as a default argument, so a test can
        # point `QUOTA_FILE` somewhere temporary and not write the real log.
        self.path = path or QUOTA_FILE
        self.limit = limit
        # `hard` is only ever true for a ceiling the archive itself declared,
        # either on a page we read now or on one we read earlier today.
        self.hard = hard
        self._state = self._load()
        if self._state.get("limit_from_server"):
            self.limit = int(self._state["limit_from_server"])
            self.hard = True

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

    def over_pace(self, n: int = 1) -> bool:
        return self.used + n > self.limit

    def check(self, n: int = 1) -> None:
        """Refuse before spending -- but only against a limit the archive set.

        Our own `SOFT_DAILY` is a pace, so passing it prints a warning and
        carries on. A ceiling the archive declared on its own pages is a rule,
        and that one refuses.
        """
        if not self.over_pace(n):
            return
        if self.hard:
            raise QuotaExhausted(
                f"les {self.limit} consultes d'avui ({self._state['day']}) estan gastades "
                f"({self.used} fetes). AQUEST SOSTRE EL DIU L'ARXIU a la seva pàgina, "
                f"no nosaltres, i no es força: torna demà, o mira si el que busques ja "
                f"és a la memòria cau."
            )
        print(
            f"  avís: {self.used + n} consultes avui, per damunt del pas de {self.limit} "
            f"que has triat. No és cap sostre de l'arxiu, però val la pena saber-ho. "
            f"Continuo."
        )

    def spend(self, what: str, search: dict | None = None) -> None:
        """Count one query and write it down.

        `what` is prose for a human to read. `search` is the same query as
        **terms**, and it is the half that a program can compare tomorrow:
        `tools.apv.verify.asked_before` reads exactly this key and skips every
        entry that lacks it, because prose describing a search is not the
        search. Without it a lookup that came back empty leaves no trace at all
        -- no transcription in `Fonts/`, no structured entry here -- and the
        plan proposes it again the next day.

        So an omitted `search` is not a small loss of detail: it is the
        difference between a zero that is recorded and a zero that is paid for
        twice. Only `--record`, which takes free prose, is entitled to omit it.
        """
        self._state["used"] = self.used + 1
        entry = {"what": what, "at": time.strftime("%H:%M:%S")}
        if search:
            entry["search"] = search
        self._state.setdefault("log", []).append(entry)
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
            # The archive has declared a ceiling on its own page. That outranks
            # whatever pace you picked, and from here on it is enforced.
            self.limit = int(limit.group(1))
            self.hard = True
            self._state["limit"] = self.limit
            self._state["limit_from_server"] = self.limit
        self._save()
        return theirs

    def summary(self) -> str:
        said = self._state.get("server_said")
        extra = f", l'arxiu deia {said}" if said is not None else ""
        kind = "sostre de l'arxiu" if self.hard else "pas propi"
        return (f"{self.used}/{self.limit} consultes avui "
                f"({self._state['day']}{extra}) · {kind}")


class Session:
    """One lookup at a time, cached forever, and every one of them counted.

    Counted for the record, not against a ration -- see the header for why
    there is no confirmed daily ceiling on this archive.
    """

    def __init__(self, cache_dir: Path | None = None, limit: int = SOFT_DAILY,
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
    parser.add_argument("--limit", type=int, default=SOFT_DAILY,
                        help=f"el teu pas diari de consultes (per defecte "
                             f"{SOFT_DAILY}). Passar-lo avisa i continua: no és cap "
                             "sostre de l'arxiu. Es pot pujar i baixar")
    parser.add_argument("--dry-run", action="store_true",
                        help="no demana res: només diu què demanaria")
    parser.add_argument("--quota", action="store_true",
                        help="diu quantes consultes queden avui i para")
    parser.add_argument("--record", metavar="QUÈ", action="append", default=[],
                        help="apunta una consulta feta A MÀ al navegador. Val la pena "
                             "encara que no hi haja sostre: el registre és el que "
                             "evita tornar a demanar una cerca que ja va tornar "
                             "buida. Repetible.")


def build_session(args: argparse.Namespace) -> Session:
    # No clamp: there is no confirmed archive ceiling to defend here. A limit
    # the archive declares still wins, but it arrives through Quota.reconcile.
    limit = int(getattr(args, "limit", SOFT_DAILY) or SOFT_DAILY)
    return Session(limit=limit, dry_run=bool(getattr(args, "dry_run", False)))

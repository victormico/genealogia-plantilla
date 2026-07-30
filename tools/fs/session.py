"""Authenticated, throttle-aware, cached session against the FamilySearch API.

Modelled on getmyancestors' `classes/session.py`, with three changes:

  1. The OAuth scope includes `openid`. FamilySearch's IdP started requiring it
     in spring 2026; without it the token exchange fails with "unable to
     authenticate client". The installed getmyancestors 1.1.2 predates the fix
     and is broken for that reason.
  2. A throttle governor. FamilySearch throttles on server *processing time*,
     not request count, and reports it per response in `X-PROCESSING-TIME`. We
     track a rolling window and sleep before we get anywhere near the limit.
  3. A persistent response cache, so re-running reports costs zero requests.

Scope of use: authenticated personal research on one's own family tree, at a
deliberately low rate, with everything cached to avoid re-fetching. This is not
a bulk harvester and must not be turned into one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import deque
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

from .. import config

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache"

API_BASE = "https://api.familysearch.org"
IDENT = "https://ident.familysearch.org"

# A third party's registered app key (Misbach's fs-auth demo). It is what every
# open-source FamilySearch tool uses, and it will stop working sooner or later.
# When it does, use --token to supply a Bearer token from a real browser login.
DEFAULT_CLIENT_ID = "a02j000000KTRjpAAH"
DEFAULT_REDIRECT_URI = "https://misbach.github.io/fs-auth/index_raw.html"

# `openid` is the fix. Do not remove it.
SCOPE = "openid profile email qualifies_for_affiliate_account country"

# FamilySearch allows roughly 18 s of server processing per minute per user.
# Stay well under it: this is someone's account, not a load test.
BUDGET_SECONDS = 10.0
WINDOW_SECONDS = 60.0

# Who we say we are, built from `projecte:` and `contacte:` in config.yaml. An
# archive that can see who is calling and why can ask us to slow down instead of
# blocking the range, so filling the contact in is worth the ten seconds.
USER_AGENT = config.user_agent("familysearch")


class ThrottleGovernor:
    """Keeps rolling server-processing-time under budget, pre-emptively."""

    def __init__(self, budget: float = BUDGET_SECONDS, window: float = WINDOW_SECONDS):
        self.budget = budget
        self.window = window
        self._samples: deque[tuple[float, float]] = deque()  # (when, seconds)
        self.total_processing = 0.0
        self.sleeps = 0

    def _prune(self, now: float) -> None:
        while self._samples and now - self._samples[0][0] > self.window:
            self._samples.popleft()

    def spent(self) -> float:
        now = time.monotonic()
        self._prune(now)
        return sum(s for _, s in self._samples)

    def wait_turn(self) -> None:
        """Block until there is room in the window for another request."""
        while True:
            now = time.monotonic()
            self._prune(now)
            spent = sum(s for _, s in self._samples)
            if spent < self.budget or not self._samples:
                return
            oldest = self._samples[0][0]
            nap = max(0.5, self.window - (now - oldest))
            self.sleeps += 1
            time.sleep(nap)

    def record(self, seconds: float) -> None:
        self.total_processing += seconds
        self._samples.append((time.monotonic(), seconds))


class FamilySearchError(RuntimeError):
    pass


class Session:
    """A logged-in FamilySearch API session."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        token: str | None = None,
        client_id: str = DEFAULT_CLIENT_ID,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        cache_dir: Path | None = None,
        use_cache: bool = True,
        max_requests: int = 300,
        timeout: int = 60,
        verbose: bool = False,
    ):
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": USER_AGENT})
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.timeout = timeout
        self.verbose = verbose
        self.max_requests = max_requests
        self.requests_made = 0
        self.cache_hits = 0
        self.governor = ThrottleGovernor()
        self.fid: str | None = None
        self.display_name: str | None = None
        self.lang: str | None = None
        # The contributor id this account signs its edits with. Anything in the
        # tree attributed to it was entered by the user, not by a stranger.
        self.tree_user_id: str | None = None
        # Endpoints that returned 403 (uncertified app). Recorded so callers can
        # degrade gracefully instead of retrying a permission we do not have.
        self.forbidden: set[str] = set()
        # Last HTTP status per path, so a None result can be explained: 204 means
        # "no results", 403 means "not permitted", 404 means "no such thing".
        self.last_status: dict[str, int] = {}

        self.cache = None
        if use_cache:
            import diskcache

            self.cache = diskcache.Cache(str(cache_dir or CACHE_DIR / "api"))

        self.token = token
        if self.token:
            self.http.headers["Authorization"] = f"Bearer {self.token}"
            self.log("using a supplied Bearer token; skipping scripted login")
        else:
            user = username or os.environ.get("FAMILY_SEARCH_USERNAME")
            pwd = password or os.environ.get("FAMILY_SEARCH_PASSWORD")
            if not user or not pwd:
                raise FamilySearchError(
                    "no credentials: set FAMILY_SEARCH_USERNAME and "
                    "FAMILY_SEARCH_PASSWORD (see .env) or pass --token"
                )
            self._login(user, pwd)
        self._set_current()

    # -- logging ----------------------------------------------------------

    def log(self, msg: str) -> None:
        if self.verbose:
            print(f"[fs] {msg}", file=sys.stderr)

    # -- authentication ---------------------------------------------------

    def _login(self, username: str, password: str) -> None:
        """Four-step scripted login: XSRF -> form post -> auth code -> token."""
        self.log("fetching login page for XSRF token")
        self.http.get(f"https://www.familysearch.org/auth/familysearch/login", timeout=self.timeout)
        xsrf = self.http.cookies.get("XSRF-TOKEN")
        if not xsrf:
            raise FamilySearchError("no XSRF-TOKEN cookie; the login page changed")

        self.log("posting credentials")
        res = self.http.post(
            f"{IDENT}/login",
            data={"_csrf": xsrf, "username": username, "password": password},
            timeout=self.timeout,
        )
        res.raise_for_status()

        self.log("requesting authorization code")
        res = self.http.get(
            f"{IDENT}/cis-web/oauth2/v3/authorization",
            params={
                "response_type": "code",
                "scope": SCOPE,
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "username": username,
            },
            timeout=self.timeout,
        )
        res.raise_for_status()
        codes = parse_qs(urlparse(res.url).query).get("code")
        if not codes:
            raise FamilySearchError(
                "no authorization code returned. FamilySearch is most likely "
                "showing a CAPTCHA, a 2FA challenge or a consent screen.\n"
                "Log in with a real browser, copy the Bearer token from a "
                "familysearch.org API request, and re-run with --token.\n"
                f"last URL: {res.url}"
            )

        self.log("exchanging code for access token")
        res = self.http.post(
            f"{IDENT}/cis-web/oauth2/v3/token",
            data={
                "grant_type": "authorization_code",
                "client_id": self.client_id,
                "code": codes[0],
                "redirect_uri": self.redirect_uri,
            },
            timeout=self.timeout,
        )
        data = res.json()
        if "access_token" not in data:
            raise FamilySearchError(f"token exchange failed: {data}")
        self.token = data["access_token"]
        self.http.headers["Authorization"] = f"Bearer {self.token}"
        self.log("authenticated")

    def _set_current(self) -> None:
        data = self.get("/platform/users/current")
        if not data or "users" not in data:
            raise FamilySearchError("authenticated but /users/current returned nothing")
        user = data["users"][0]
        self.fid = user.get("personId")
        self.display_name = user.get("displayName")
        self.lang = user.get("preferredLanguage")
        self.tree_user_id = user.get("treeUserId")

    # -- requests ---------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict | None = None,
        accept: str = "application/x-gedcomx-v1+json",
        refresh: bool = False,
    ) -> dict | None:
        """GET a platform path. Returns parsed JSON, or None for 204/404/403.

        Cached by (path, params, accept). Cached reads cost no request and are
        not subject to the request cap.
        """
        key = json.dumps([path, sorted((params or {}).items()), accept], sort_keys=True)
        if self.cache is not None and not refresh:
            hit = self.cache.get(key, default=None)
            if hit is not None:
                self.cache_hits += 1
                return hit["body"]

        if path in self.forbidden:
            return None
        if self.requests_made >= self.max_requests:
            raise FamilySearchError(
                f"request cap reached ({self.max_requests}). Raise --max-requests "
                "only if you really need to; the cap exists to stay polite."
            )

        attempt = 0
        while True:
            attempt += 1
            self.governor.wait_turn()
            self.requests_made += 1
            self.log(f"GET {path} {params or ''}")
            try:
                r = self.http.get(
                    API_BASE + path,
                    params=params,
                    headers={"Accept": accept},
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                if attempt >= 3:
                    raise FamilySearchError(f"GET {path} failed: {exc}") from exc
                time.sleep(5 * attempt)
                continue

            # Account for the server time this request consumed.
            try:
                self.governor.record(float(r.headers.get("X-PROCESSING-TIME", 0)) / 1000)
            except (TypeError, ValueError):
                pass

            if r.status_code in (429, 503):
                wait = float(r.headers.get("Retry-After", 30))
                self.log(f"{r.status_code} throttled; sleeping {wait:.0f}s")
                if attempt >= 4:
                    raise FamilySearchError(f"GET {path}: still {r.status_code} after {attempt} tries")
                time.sleep(wait)
                continue

            self.last_status[path] = r.status_code
            if r.status_code == 204:
                # Search and matches endpoints answer 204 for "no results".
                body = None
            elif r.status_code == 406:
                raise FamilySearchError(
                    f"406 for {path}: wrong Accept header ({accept}). The matches "
                    "and search endpoints answer in application/x-gedcomx-atom+json."
                )
            elif r.status_code == 403:
                # Almost always "this app is not certified for that collection".
                self.forbidden.add(path)
                self.log(f"403 forbidden: {path} — recording and degrading")
                return None
            elif r.status_code in (404, 410):
                self.log(f"{r.status_code} not found: {path}")
                return None
            elif r.status_code == 401:
                raise FamilySearchError(
                    "401 unauthorized: the token expired or was rejected. "
                    "Re-run to log in again, or pass a fresh --token."
                )
            else:
                r.raise_for_status()
                try:
                    body = r.json()
                except ValueError:
                    raise FamilySearchError(f"GET {path}: response was not JSON")

            if self.cache is not None:
                self.cache.set(key, {"body": body, "status": r.status_code})
            return body

    def stats(self) -> str:
        return (
            f"{self.requests_made} requests, {self.cache_hits} cache hits, "
            f"{self.governor.total_processing:.1f}s server time, "
            f"{self.governor.sleeps} pre-emptive sleeps"
        )


def load_env(path: Path = ROOT / ".env") -> None:
    """Read KEY=VALUE lines from .env into the environment. Values never logged."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


def build_session(args: argparse.Namespace) -> Session:
    load_env()
    return Session(
        token=getattr(args, "token", None),
        use_cache=not getattr(args, "no_cache", False),
        max_requests=getattr(args, "max_requests", 300),
        verbose=getattr(args, "verbose", False),
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--token", help="Bearer token from a real browser login")
    parser.add_argument("--no-cache", action="store_true", help="bypass the response cache")
    parser.add_argument("--max-requests", type=int, default=300, help="hard request cap [300]")
    parser.add_argument("-v", "--verbose", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(description="FamilySearch session check")
    add_common_args(parser)
    parser.add_argument("--whoami", action="store_true", help="print the logged-in user")
    args = parser.parse_args()

    try:
        fs = build_session(args)
    except FamilySearchError as exc:
        print(f"login failed:\n{exc}", file=sys.stderr)
        return 1

    print(f"logged in as {fs.display_name} ({fs.fid}), language {fs.lang}")
    print(fs.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())

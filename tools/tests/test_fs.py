"""Offline tests for the FamilySearch client.

The throttle governor is tested with synthetic timings rather than by hitting
FamilySearch's `/platform/throttled` test endpoint: deliberately tripping rate
limits on a real account to exercise defensive code is not a good trade.

    python3 -m tools.tests.test_fs
"""

from __future__ import annotations

import sys
import time

from tools.fs.api import _search_params
from tools.fs.session import ThrottleGovernor

_failures: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label}{': ' + detail if detail else ''}")
        _failures.append(label)


def test_search_params() -> None:
    print("\nsearch parameter mapping")
    p = _search_params({"given_name": "Rita", "surname": "Segarra Molins"})
    check(p == {"q.givenName": "Rita", "q.surname": "Segarra Molins"}, "q. terms", str(p))

    p = _search_params({"birth_like_place": "Ontinyent, València, Espanya"})
    check(
        p == {"q.birthLikePlace": "Ontinyent, València, Espanya"},
        "multi-word term becomes camelCase",
        str(p),
    )

    p = _search_params({"f_collection_id": "1234", "c_gender": "on"})
    check(p == {"f.collectionId": "1234", "c.gender": "on"}, "f. and c. categories", str(p))

    p = _search_params({"father_surname": "Segarra", "mother_given_name": ""})
    check(p == {"q.fatherSurname": "Segarra"}, "empty values dropped", str(p))


def test_governor_allows_under_budget() -> None:
    print("\nthrottle governor: under budget")
    g = ThrottleGovernor(budget=10.0, window=60.0)
    started = time.monotonic()
    for _ in range(5):
        g.wait_turn()
        g.record(0.5)  # 5 requests x 0.5s = 2.5s, well under 10s
    elapsed = time.monotonic() - started
    check(elapsed < 0.5, "no sleeping while under budget", f"{elapsed:.2f}s")
    check(abs(g.spent() - 2.5) < 0.01, "tracks 2.5s spent", f"{g.spent():.2f}")
    check(g.sleeps == 0, "no pre-emptive sleeps")


def test_governor_sleeps_over_budget() -> None:
    print("\nthrottle governor: over budget")
    # A 2s window keeps the test fast while exercising the same code path.
    g = ThrottleGovernor(budget=1.0, window=2.0)
    g.wait_turn()
    g.record(5.0)  # one very expensive request blows the budget
    check(g.spent() > 1.0, "budget exceeded", f"{g.spent():.1f}s")

    started = time.monotonic()
    g.wait_turn()  # must block until the window rolls past the sample
    elapsed = time.monotonic() - started
    check(elapsed >= 0.5, "blocked before the next request", f"{elapsed:.2f}s")
    check(g.sleeps >= 1, "recorded a pre-emptive sleep", str(g.sleeps))
    check(g.spent() == 0.0, "window pruned once elapsed", f"{g.spent():.2f}")
    check(g.total_processing == 5.0, "lifetime total still counted")


def test_governor_never_deadlocks() -> None:
    print("\nthrottle governor: empty window")
    # A single request larger than the whole budget must still be allowed
    # through rather than blocking for ever.
    g = ThrottleGovernor(budget=0.1, window=3600.0)
    started = time.monotonic()
    g.wait_turn()
    check(time.monotonic() - started < 0.2, "first request never blocks")


def main() -> int:
    test_search_params()
    test_governor_allows_under_budget()
    test_governor_sleeps_over_budget()
    test_governor_never_deadlocks()
    print()
    if _failures:
        print(f"{len(_failures)} FAILED: {', '.join(_failures)}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

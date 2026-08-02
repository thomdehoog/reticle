"""The ceiling on request rate, and the two ways it fails.

It fails *open* by being too generous to stop anything, and it fails *closed* by
locking out the facility it was meant to protect. The second is much worse and
much likelier: a limit that blocks an author saving their work gets switched
off, and then there is no limit at all.

So the window is tested directly, with an injected clock, rather than by firing
hundreds of requests through the application and hoping. That makes the
boundary conditions assertable — the exact request that is refused, the moment
the allowance returns — which is the part that decides whether the numbers in
``settings`` are safe.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import pytest

from app.ratelimit import WINDOW_SECONDS, RateLimitMiddleware, SlidingWindow


class Clock:
    """A hand-wound clock, so a one-minute window takes no time to test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def window():
    return SlidingWindow()


@pytest.fixture
def clock():
    return Clock()


# --- the window ------------------------------------------------------------


def test_requests_under_the_limit_are_allowed(window, clock):
    for _ in range(5):
        assert window.check("user", limit=5, now=clock.advance(1)).allowed


def test_the_request_past_the_limit_is_refused(window, clock):
    for _ in range(5):
        window.check("user", limit=5, now=clock.advance(1))

    assert window.check("user", limit=5, now=clock.advance(1)).allowed is False


def test_the_allowance_returns_as_the_window_slides(window, clock):
    """The distinguishing property. A fixed window would refuse everything
    until the boundary and then allow a full burst; this lets exactly as much
    through as has aged out."""
    for _ in range(5):
        window.check("user", limit=5, now=clock.advance(1))
    assert window.check("user", limit=5, now=clock.now).allowed is False

    # The five hits landed one second apart, at t+1 .. t+5. Advancing to a
    # cutoff that sits between the first and the second ages out exactly one of
    # them, so exactly one slot should reopen — not two, and not the whole
    # allowance.
    later = clock.advance(WINDOW_SECONDS - 3.5)

    assert window.check("user", limit=5, now=later).allowed is True
    assert window.check("user", limit=5, now=later).allowed is False


def test_a_burst_at_the_boundary_cannot_double_the_rate(window, clock):
    """What a fixed window gets wrong: the full allowance in the last second of
    one window and again in the first second of the next, which is twice the
    intended rate at exactly the moment somebody is trying to abuse it."""
    for _ in range(10):
        window.check("user", limit=10, now=clock.now)

    barely_later = clock.advance(WINDOW_SECONDS * 0.99)

    assert window.check("user", limit=10, now=barely_later).allowed is False


def test_one_caller_does_not_consume_another_s_allowance(window, clock):
    for _ in range(5):
        window.check("alice", limit=5, now=clock.advance(1))

    assert window.check("bob", limit=5, now=clock.now).allowed is True


def test_the_retry_after_is_long_enough_to_actually_help(window, clock):
    """A Retry-After that is a fraction short invites an immediate retry that
    fails again, which is how a limiter turns one runaway client into a hot
    loop."""
    for _ in range(3):
        window.check("user", limit=3, now=clock.now)

    decision = window.check("user", limit=3, now=clock.now)

    assert decision.allowed is False
    assert 1 <= decision.retry_after <= WINDOW_SECONDS + 1


def test_idle_keys_are_forgotten_rather_than_accumulating(window, clock):
    """Without pruning the dictionary grows one entry per address seen, for the
    life of the process — a slow leak wearing a limiter's clothes."""
    for index in range(50):
        window.check(f"visitor-{index}", limit=5, now=clock.now)
    assert len(window._hits) == 50

    window.prune(now=clock.advance(WINDOW_SECONDS + 1))

    assert window._hits == {}


def test_pruning_keeps_a_caller_who_is_still_active(window, clock):
    window.check("busy", limit=5, now=clock.now)
    window.check("gone", limit=5, now=clock.now)
    clock.advance(WINDOW_SECONDS + 1)
    window.check("busy", limit=5, now=clock.now)

    window.prune(now=clock.now)

    assert set(window._hits) == {"busy"}


# --- how the middleware classifies a request -------------------------------


class Settings:
    rate_limit_enabled = True
    rate_limit_reads_per_minute = 600
    rate_limit_writes_per_minute = 240
    rate_limit_uploads_per_minute = 60


@pytest.fixture
def middleware():
    return RateLimitMiddleware(app=None, settings=Settings())


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        ("/api/guides", "GET", ("read", 600)),
        ("/api/guides", "POST", ("write", 240)),
        ("/api/media", "POST", ("upload", 60)),
        ("/api/media/01ABC", "GET", ("read", 600)),
    ],
)
def test_an_upload_is_held_to_a_lower_ceiling_than_a_page_view(middleware, path, method, expected):
    """A guide's worth of photographs is tens of megabytes and every one is
    decoded and re-encoded. A limit generous enough for reads would let a loop
    fill the disk.

    Bucket and limit come back together, so the pair can never disagree — a
    request counted against the upload bucket but measured against the read
    limit would be an upload ceiling that does not exist.
    """
    assert middleware._allowance(path, method) == expected


def test_exhausting_one_allowance_does_not_close_the_others(middleware):
    """A reader who has hit the read ceiling must still be able to sign out."""
    buckets = {
        middleware._allowance("/api/guides", "GET")[0],
        middleware._allowance("/api/guides", "POST")[0],
        middleware._allowance("/api/media", "POST")[0],
    }

    assert buckets == {"read", "write", "upload"}


def test_a_caller_is_counted_by_address_and_not_by_a_cookie_they_choose(middleware):
    """Keying on the session cookie is the obvious idea and it is bypassable.

    The cookie value is not checked against the session table until much later,
    so a caller can send a fresh random one on every request and land in a new
    bucket each time - defeating the limit entirely and, worse, adding a
    dictionary entry per request that they control. The address is the only
    part of a request the caller cannot choose.
    """
    with_cookie = {
        "client": ("10.0.0.1", 5000),
        "headers": [(b"cookie", b"reticle_session=a-freshly-invented-value")],
    }
    without = {"client": ("10.0.0.1", 5000), "headers": []}

    assert middleware._identify(with_cookie) == middleware._identify(without)


def test_two_addresses_get_separate_allowances(middleware):
    first = {"client": ("10.0.0.1", 5000), "headers": []}
    second = {"client": ("10.0.0.2", 5000), "headers": []}

    assert middleware._identify(first) != middleware._identify(second)


def test_a_caller_with_no_address_at_all_is_still_counted(middleware):
    """ASGI permits a missing client. Returning None would make every such
    request share a key with every other, or crash on the join."""
    assert middleware._identify({"headers": []}) == "unknown"


def test_the_number_of_tracked_callers_is_capped(clock):
    """Otherwise a flood from many addresses grows the window dictionary until
    the process runs out of memory - the limiter becoming the outage it was
    added to prevent."""
    window = SlidingWindow(max_keys=50)

    for index in range(500):
        window.check(f"10.0.{index // 256}.{index % 256}", limit=100, now=clock.now)

    assert len(window._hits) <= 50


def test_a_caller_already_being_tracked_is_not_refused_by_the_cap(clock):
    """The cap must bite on new keys only. Refusing a caller who is already
    inside their allowance would turn a flood elsewhere into an outage for
    everybody."""
    window = SlidingWindow(max_keys=2)
    window.check("10.0.0.1", limit=10, now=clock.now)
    window.check("10.0.0.2", limit=10, now=clock.now)

    assert window.check("10.0.0.1", limit=10, now=clock.advance(1)).allowed is True


def test_a_full_table_evicts_the_stalest_key_rather_than_refusing_the_newcomer(clock):
    """A newcomer is as likely to be a colleague as part of the flood.

    Keys are ``address:bucket``, so one caller already inside the table holds up
    to three of them — and the first save of the day asks for a bucket that
    caller has never used. Refusing on a full table answered 429 to somebody who
    had sent one request, which is an outage rather than a limit.
    """
    window = SlidingWindow(max_keys=2)
    window.check("10.0.0.1:read", limit=10, now=clock.now)
    window.check("10.0.0.1:write", limit=10, now=clock.advance(1))

    arriving = window.check("10.0.0.2:read", limit=10, now=clock.advance(1))

    assert arriving.allowed is True
    assert len(window._hits) == 2
    assert "10.0.0.1:read" not in window._hits  # the stalest, so the one evicted


# --- through the real application ------------------------------------------


def test_a_flood_of_reads_is_eventually_refused_with_a_retry_after(author, monkeypatch):
    """One end-to-end check that the middleware is actually mounted.

    The limit is lowered rather than the request count raised: the point is the
    wiring, and firing six hundred requests to prove it would add a minute to
    every run.
    """
    from app.main import app

    for middleware in _mounted(app):
        monkeypatch.setattr(middleware.settings, "rate_limit_enabled", True, raising=False)
        monkeypatch.setattr(middleware.settings, "rate_limit_reads_per_minute", 3, raising=False)
        middleware.window = SlidingWindow()

    for _ in range(3):
        assert author.get("/api/auth/me").status_code == 200

    refused = author.get("/api/auth/me")

    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate_limited"
    assert int(refused.headers["Retry-After"]) >= 1
    assert refused.json()["requestId"]


def test_the_probes_are_never_rate_limited(anon, monkeypatch):
    """An orchestrator polls these every few seconds by design. Throttling a
    readiness check pulls the instance out of the load balancer for being
    healthy."""
    from app.main import app

    for middleware in _mounted(app):
        monkeypatch.setattr(middleware.settings, "rate_limit_enabled", True, raising=False)
        monkeypatch.setattr(middleware.settings, "rate_limit_reads_per_minute", 2, raising=False)
        middleware.window = SlidingWindow()

    for _ in range(10):
        assert anon.get("/api/health").status_code == 200


def _mounted(app):
    """The mounted RateLimitMiddleware instances, however Starlette nests them."""
    found = []
    stack = [app.middleware_stack]
    seen = set()
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, RateLimitMiddleware):
            found.append(current)
        for attribute in ("app", "next", "_app"):
            stack.append(getattr(current, attribute, None))
    assert found, "the rate limiter is not mounted at all"
    return found

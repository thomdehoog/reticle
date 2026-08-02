"""A ceiling on how fast one caller can hit the API.

Login already has its own throttle, backed by a table, because a failed login
is an attack signal worth keeping across restarts and worth counting per email
as well as per address. This is the other half: everything that is *not* a
login, where the concern is not credential guessing but one account — or one
stolen session — making the server unusable for the twenty people who need it.

Three things this is honest about:

**It is per process.** The window lives in memory. Two workers give twice the
configured rate, and a restart forgets everything. That is the correct trade at
this size: the alternative is a round trip to the database on every request, to
defend a single-server installation against a threat that a shared counter
would only bound more precisely. When Reticle runs more than one process behind
a load balancer, this moves to Redis — and the interface here is the seam for
that.

**It is not a security boundary.** It stops a runaway script and a stuck retry
loop. It does not stop somebody determined, who can change address.

**It must never lock out the facility.** The limits are set where a person
cannot reach them and a loop can. An author saving every few seconds, a reader
opening thirty guides, an importer pushing a corpus — all of those have to pass
untouched, because a system that blocks real work to defend against theoretical
work will be turned off.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from . import errors
from .auth import SAFE_METHODS
from .observability import REQUEST_ID_HEADER, request_id

WINDOW_SECONDS = 60.0

MAX_TRACKED_KEYS = 20_000
"""How many distinct callers are tracked at once.

Each key costs roughly a kilobyte, so this is about 20 MB - far more addresses
than a university facility will ever have, and small enough that a flood cannot
turn the limiter into the memory exhaustion it was added to prevent.
"""

# Uploads get their own, much lower ceiling. A guide's worth of photographs is
# tens of megabytes and every one is decoded and re-encoded, so the cost of an
# upload is nothing like the cost of a page view — and a limit generous enough
# for reads would let a loop exhaust the disk.
UPLOAD_PATH = "/api/media"


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: int = 0


class SlidingWindow:
    """Timestamps per key, trimmed to the window on each check.

    A fixed window would let a caller send the full allowance in the last
    second of one window and again in the first second of the next — twice the
    intended rate at exactly the moment it matters. Keeping the timestamps
    costs a deque of at most ``limit`` floats per active key.
    """

    def __init__(self, max_keys: int = MAX_TRACKED_KEYS) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self.max_keys = max_keys

    def check(self, key: str, limit: int, now: float | None = None) -> Decision:
        moment = time.monotonic() if now is None else now

        # A hard ceiling on how many callers are tracked at once. Without it a
        # flood from many addresses grows this dictionary until the process
        # runs out of memory - the limiter becoming the outage it exists to
        # prevent. Past the ceiling, prune first; if that frees nothing, refuse
        # rather than grow.
        if key not in self._hits and len(self._hits) >= self.max_keys:
            self.prune(moment)
            if len(self._hits) >= self.max_keys:
                return Decision(False, retry_after=int(WINDOW_SECONDS))

        hits = self._hits[key]

        cutoff = moment - WINDOW_SECONDS
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= limit:
            # How long until the oldest hit falls out of the window. Rounded up,
            # because a Retry-After that is a fraction short invites an
            # immediate retry that fails again.
            return Decision(False, retry_after=max(1, int(hits[0] - cutoff) + 1))

        hits.append(moment)
        return Decision(True)

    def forget(self, key: str) -> None:
        self._hits.pop(key, None)

    def prune(self, now: float | None = None) -> None:
        """Drop keys with nothing left in the window.

        Without this the dictionary grows one entry per address seen, forever,
        which on a long-running server is a slow leak rather than a limiter.
        """
        moment = time.monotonic() if now is None else now
        cutoff = moment - WINDOW_SECONDS
        for key in [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]


class RateLimitMiddleware:
    """Applies the window, and refuses with 429 rather than a generic error.

    Raw ASGI so it runs before routing and before any body is read: the point
    of a limit is to be cheap, and a limiter that first lets the request be
    parsed has already paid most of the cost it was meant to avoid.

    The key is the session cookie where there is one, and the client address
    otherwise. Using the cookie means one signed-in user on a shared
    institutional NAT cannot exhaust the allowance of everyone behind it —
    which, at a university, is the normal case rather than the exotic one.
    """

    def __init__(self, app: ASGIApp, settings) -> None:
        self.app = app
        self.settings = settings
        self.window = SlidingWindow()
        self._requests_since_prune = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # The probes are exempt. An orchestrator polls them every few seconds
        # by design, and rate-limiting a readiness check means the instance is
        # pulled out of the load balancer for being healthy.
        if path in ("/api/health", "/api/ready"):
            await self.app(scope, receive, send)
            return

        # Login has its own throttle, which counts per email as well as per
        # address and survives a restart. Applying this one too would only
        # blur that.
        if path == "/api/auth/login":
            await self.app(scope, receive, send)
            return

        limit = self._limit_for(path, method)
        decision = self.window.check(f"{self._identify(scope)}:{self._bucket(path, method)}", limit)

        self._maybe_prune()

        if not decision.allowed:
            failure = errors.ApiError(
                "rate_limited", "Too many requests. Wait a moment and try again."
            )
            body = {**failure.body(), "requestId": request_id.get()}
            response = JSONResponse(
                status_code=429,
                content=body,
                headers={
                    "Retry-After": str(decision.retry_after),
                    REQUEST_ID_HEADER: request_id.get(),
                },
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _limit_for(self, path: str, method: str) -> int:
        if path.startswith(UPLOAD_PATH) and method not in SAFE_METHODS:
            return self.settings.rate_limit_uploads_per_minute
        if method in SAFE_METHODS:
            return self.settings.rate_limit_reads_per_minute
        return self.settings.rate_limit_writes_per_minute

    def _bucket(self, path: str, method: str) -> str:
        """Separate allowances, so exhausting one does not close the others.

        A reader who has hit the read ceiling must still be able to sign out,
        and an importer saturating uploads must not stop anybody reading.
        """
        if path.startswith(UPLOAD_PATH) and method not in SAFE_METHODS:
            return "upload"
        return "read" if method in SAFE_METHODS else "write"

    def _identify(self, scope: Scope) -> str:
        """Which bucket this request counts against.

        The address, always - never the session cookie. Keying on the cookie is
        the obvious idea and it is wrong twice over. A caller can invent a fresh
        cookie value per request, and since the value is not checked against the
        session table until much later, every request would land in a brand new
        bucket and the limit would not exist at all. The same trick fills the
        window dictionary with one entry per request, which is a memory leak an
        anonymous caller controls.

        Keying on the address means a shared institutional NAT shares one
        allowance. That is a real cost, and it is why the limits are set high
        enough that ordinary use never reaches them: the job here is to stop a
        runaway script, not to ration colleagues.
        """
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _maybe_prune(self) -> None:
        self._requests_since_prune += 1
        if self._requests_since_prune >= 1000:
            self._requests_since_prune = 0
            self.window.prune()

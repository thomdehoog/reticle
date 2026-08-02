"""Logging, request correlation and the probes an orchestrator reads.

The gap this closes: when somebody reports "it broke around eleven", the answer
has to come from somewhere. Before this there was one logger, in ``auth``, and
one warning in it — so the honest answer was "nothing was recorded".

Three decisions worth stating, because each has a tempting wrong version.

**JSON, not prose.** A line like ``PUT /api/guides/01H… 500 in 2.1s`` is
readable by a person and useless to everything else. Nobody greps a year of
logs by hand. One JSON object per line costs nothing to emit, stays readable
enough in a terminal, and can be shipped to anything later without rewriting
the application. The format is stable: renaming a field breaks somebody's alert.

**A request id on every line, and in the response.** A user reporting a failure
can quote the id from the error they saw, which turns "it broke around eleven"
into one exact request. It is generated here rather than trusted from the
client, unless it arrives from a proxy that is already tracing.

**Never log the body, the query string, or a header.** Reticle's requests carry
passwords on the login endpoint, session cookies on every endpoint, and search
terms that are themselves institute business. A log that captures those turns
every future log reader into somebody who can sign in. Method, path template,
status, duration, and who — nothing else.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# A ContextVar rather than a global: under async, several requests are in flight
# in one process at once, and a module-level variable would attribute a log line
# to whichever request happened to run last.
request_id: ContextVar[str] = ContextVar("request_id", default="-")

# Fields ``logging`` puts on every record. Anything outside this set was passed
# by the caller via ``extra=`` and belongs in the JSON output.
_STANDARD = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with whatever the caller attached.

    Uses ``default=str`` so a value that is not JSON-serialisable degrades to
    its repr instead of raising. A logging call must never be the thing that
    takes down the request it was describing.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "requestId": request_id.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter as the only handler on the root logger.

    Replaces existing handlers rather than adding to them: uvicorn installs its
    own, and leaving both attached prints every line twice — once as JSON and
    once as prose — which doubles the volume and makes the JSON stream invalid
    for anything parsing it.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # uvicorn's access log is switched off rather than reformatted, and this is
    # a privacy decision rather than a tidiness one: it logs the raw request
    # line, which includes the query string — so every search anybody performs
    # would be written to disk verbatim. On this application a search term is
    # institute business ("unpublished cryo results"), and there is no way to
    # keep the line and drop the query.
    #
    # Nothing is lost. RequestContextMiddleware logs every request with its
    # method, route template, status and duration, which is what the access log
    # was for, minus the part that leaks.
    access = logging.getLogger("uvicorn.access")
    access.handlers = []
    access.propagate = False
    access.disabled = True

    # SQLAlchemy at INFO logs every statement it emits, which on this
    # application means the full text of a guide on every save.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # httpx logs the full URL of any request made *by* this process, query
    # string included. The importer uses it against a migration source, so the
    # URLs are somebody else's — and a redirect chain in a log is still a log
    # of what was fetched.
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestContextMiddleware:
    """Assign an id, time the request, log the outcome exactly once.

    Raw ASGI rather than ``BaseHTTPMiddleware`` for a specific reason: the
    latter runs the downstream app in a separate task, and a ``ContextVar`` set
    in the middleware is not visible to the endpoint. The whole point is that
    the id reaches the log lines the handler writes, so it has to be set in the
    same context the handler runs in.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.log = logging.getLogger("reticle.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope, REQUEST_ID_HEADER)
        # A client-supplied id is echoed only if it looks like an id. It ends up
        # in log files, so an arbitrary string would let a caller inject
        # newlines and forge log entries.
        identifier = incoming if incoming and _plausible(incoming) else uuid.uuid4().hex
        token = request_id.set(identifier)
        started = time.perf_counter()
        status_holder = {"status": 500}

        wanted = REQUEST_ID_HEADER.lower().encode()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = message.setdefault("headers", [])
                # Only if the response does not already carry one. Error
                # responses set it themselves so it can also go in the body,
                # and appending unconditionally produced a duplicate header —
                # which httpx joins into "id, id" and a client parses as one
                # malformed value.
                if not any(key == wanted for key, _ in headers):
                    headers.append((wanted, identifier.encode()))
            await send(message)

        # Both log calls happen before the ContextVar is reset, because the
        # formatter reads the id from it. Emitting the success line after the
        # `finally` stamped every completed request with "-" — the id was in
        # the response header and missing from the log line meant to match it.
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Logged here and re-raised: this is the only place that sees both
            # the failure and the request that caused it. Without it an
            # unhandled error is a 500 with no record of what was being asked.
            self.log.exception("request failed", extra=self._fields(scope, 500, started))
            raise
        else:
            self.log.info("request", extra=self._fields(scope, status_holder["status"], started))
        finally:
            request_id.reset(token)

    def _fields(self, scope: Scope, status: int, started: float) -> dict[str, Any]:
        # The *route template* where one is available — ``/api/guides/{guide_id}``
        # rather than the resolved path. Otherwise every guide is its own
        # distinct log key, which makes the logs impossible to aggregate and
        # writes identifiers into them for no benefit.
        route = scope.get("route")
        return {
            "method": scope.get("method", ""),
            "path": getattr(route, "path", None) or scope.get("path", ""),
            "status": status,
            "durationMs": round((time.perf_counter() - started) * 1000, 1),
            "clientIp": _client_ip(scope),
        }


def _plausible(value: str) -> bool:
    return 8 <= len(value) <= 200 and all(c.isalnum() or c in "-_" for c in value)


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key == wanted:
            return value.decode("latin-1", "replace")
    return None


def _client_ip(scope: Scope) -> str | None:
    client = scope.get("client")
    return client[0] if client else None

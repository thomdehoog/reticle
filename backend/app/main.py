"""Where the application is assembled, and what every request passes through.

Reticle is ZMB's self-hosted step-by-step guide platform. The endpoints
themselves live in ``routers``; this file builds the application object out of
them and wraps it in the layers that apply to everything.

Those layers — middleware — are the substance of the file. Each one gets a look
at every request on the way in and every response on the way out: adding the
security headers, giving the request an id and logging it, refusing a body that
is too large, refusing a caller going too fast, checking the CSRF header. The
**order they are nested in is load-bearing**, and there is a diagram in
``create_app`` explaining each position. Getting it wrong is not cosmetic and it
is close to invisible: a refusal issued by an outer layer never reaches the
inner one, so a rate-limited request can go out with no id and no headers.

The other half of the file turns failures into the documented response shape.
FastAPI, Starlette and any unhandled exception each fail in their own way, and
the handlers below rewrite all of them into the one envelope ``errors`` defines.

The whole application sits behind the login. ``PUBLIC_PATHS`` is the list of
exceptions and :func:`unauthenticated_routes` walks the real routing table, so
"only those" is something a test asserts rather than something anybody hopes.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import errors
from .auth import SAFE_METHODS, get_session_row
from .db import init_db
from .observability import (
    REQUEST_ID_HEADER,
    RequestContextMiddleware,
    configure_logging,
    request_id,
)
from .ratelimit import UPLOAD_PATH, RateLimitMiddleware
from .routers import (
    auth,
    categories,
    discovery,
    export,
    guides,
    media,
    pages,
    system,
    telemetry,
    users,
)
from .security import CSRF_COOKIE, CSRF_HEADER, constant_time_equals
from .settings import get_settings

CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})

PUBLIC_PATHS = frozenset({"/api/health", "/api/ready", "/api/auth/login", "/api/config"})

STATUS_TO_CODE = {401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "not_found"}


class RequestSizeLimitMiddleware:
    """Refuse an over-long body from its declared length, before anything reads it.

    Written against the raw ASGI interface rather than as a
    ``BaseHTTPMiddleware`` so that it decides before any part of the stack has a
    reason to buffer: what allocates the body is the endpoint reading it for
    validation, and on the login endpoint that allocation is performed on behalf
    of a caller who has not authenticated and never will. Without this, a 210 MB
    login attempt is held in memory in full and only then rejected as invalid.

    Uploads get a larger cap rather than an exemption, and the body is counted
    as it arrives rather than trusted from its declared length - see
    ``_cap_for`` and the counting receive below for why each of those matters.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, upload_max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.upload_max_bytes = upload_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        cap = self._cap_for(scope)

        if self._declares_more_than(headers, cap):
            await self._refuse(cap, scope, receive, send)
            return

        # A declared length is a claim, not a fact. A request with no
        # Content-Length at all - chunked transfer encoding - carried no claim
        # to check, and one declaring a small body could simply send more. So
        # the body is also counted as it arrives, and the connection is dropped
        # the moment it passes the cap.
        counted = 0
        refused = False

        async def counting_receive() -> Message:
            nonlocal counted, refused
            message = await receive()
            if message["type"] == "http.request":
                counted += len(message.get("body", b""))
                if counted > cap:
                    refused = True
                    # Reported as the end of the body. The endpoint sees a
                    # truncated request and fails validation, and the response
                    # below replaces whatever it was going to say.
                    return {"type": "http.disconnect"}
            return message

        sent_start = False

        async def guarded_send(message: Message) -> None:
            nonlocal sent_start
            if refused and not sent_start:
                sent_start = True
                await self._refuse(cap, scope, receive, send)
                return
            if refused:
                return
            if message["type"] == "http.response.start":
                sent_start = True
            await send(message)

        await self.app(scope, counting_receive, guarded_send)

    def _cap_for(self, scope: Scope) -> int:
        """Uploads legitimately run to hundreds of megabytes; JSON does not.

        Two caps rather than an exemption, and the larger one is decided from
        the **route**, not from the content type. Keying on the header hands the
        choice to the caller: any request could take the 205 MB cap by writing
        ``Content-Type: multipart/form-data``, including one aimed at the login
        endpoint, which reads its whole body before it can tell that it is not
        JSON and which is exempt from both the rate limiter and CSRF. The path
        and the method are the parts of a request that the routing table, rather
        than the sender, decides the meaning of.
        """
        if (
            scope.get("path", "").startswith(UPLOAD_PATH)
            and scope.get("method") not in SAFE_METHODS
        ):
            return self.upload_max_bytes
        return self.max_bytes

    def _declares_more_than(self, headers: Headers, cap: int) -> bool:
        declared = headers.get("content-length")
        return bool(declared and declared.isdigit() and int(declared) > cap)

    async def _refuse(self, cap: int, scope: Scope, receive: Receive, send: Send) -> None:
        failure = errors.payload_too_large(f"Requests must be at most {_size_words(cap)}.")
        await _failure(failure.status_code, failure.body())(scope, receive, send)


class UnhandledErrorMiddleware:
    """Turn any exception nobody anticipated into the documented 500 envelope.

    This is middleware rather than an ``@app.exception_handler(Exception)``, and
    the reason is where each one sits. Starlette runs that handler in
    ``ServerErrorMiddleware``, which is the **outermost** layer of all — outside
    the one that assigns the request id and outside the one that adds the
    security headers. A 500 built there went out with ``requestId: "-"`` and no
    ``X-Content-Type-Options``, ``X-Frame-Options``, ``Referrer-Policy`` or CORS
    headers, so the one error a user is most likely to report was the one they
    could not quote an id for.

    Placed inside those two layers instead, the id is the real one and the
    headers are added on the way out.

    It re-raises once the response has begun, because at that point the status
    line is already on the wire and a second one would corrupt the stream.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def watching_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watching_send)
        except Exception:
            if started:
                raise
            # Logged, never described. The message could name a table, echo
            # submitted input, or quote a filesystem path.
            logging.getLogger("reticle").exception("unhandled error")
            failure = errors.ApiError("internal_error", "Something went wrong.")
            await _failure(500, failure.body())(scope, receive, send)


class CsrfMiddleware(BaseHTTPMiddleware):
    """Reject a mutating request whose header does not echo the CSRF cookie.

    This runs as middleware rather than as a dependency so that it cannot be
    forgotten on a new route, and so that it also covers requests that never
    reach a handler. The session-bound half of the check lives in
    ``auth.get_session_row``; this half catches the ordinary cross-site form
    post, which carries the cookie but cannot read it.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method not in SAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
            presented = request.headers.get(CSRF_HEADER)
            expected = request.cookies.get(CSRF_COOKIE)
            if not constant_time_equals(presented, expected):
                failure = errors.forbidden("Missing or invalid CSRF token.")
                return JSONResponse(status_code=failure.status_code, content=failure.body())
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Blanket hardening headers.

    The API returns JSON and images only, so it can afford the strictest
    possible policy: nothing embeds it, nothing sniffs it, no referrer leaves.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return response


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Bring the schema up to date, then start serving.

    Running migrations here means a deployment that forgets the migration step
    does not quietly serve traffic against last release's schema — see
    ``db.init_db`` for the three states it handles, and for the warning about
    destructive migrations, which should not run themselves.

    The application is marked ready only after this returns. A readiness probe
    that goes green while migrations are still running sends traffic to a
    process that cannot answer it.
    """
    settings = get_settings()
    configure_logging(settings.log_level)
    logging.getLogger("reticle").info(
        "starting", extra={"database": _redacted(settings.database_url)}
    )
    init_db()
    application.state.ready = True
    try:
        yield
    finally:
        application.state.ready = False
        logging.getLogger("reticle").info("stopped")


def _redacted(url: str) -> str:
    """The database URL with any password removed.

    ``postgresql://reticle:hunter2@db/reticle`` in a startup log is a password
    in a log, and startup logs are the ones people paste into tickets.
    """
    if "@" not in url:
        return url
    prefix, _, host = url.rpartition("@")
    scheme, _, credentials = prefix.partition("://")
    user = credentials.partition(":")[0]
    return f"{scheme}://{user}:***@{host}"


def create_app() -> FastAPI:
    """Build the application.

    The generated documentation is off unless ``RETICLE_DEBUG`` says otherwise.
    FastAPI mounts ``/docs``, ``/redoc`` and ``/openapi.json`` outside the router
    tree, so no authentication dependency touches them and no role check applies:
    on a deployed instance they published the full route inventory, every request
    and response shape and every field name to anyone who asked, unauthenticated.
    That is a map of the application handed to whoever is looking for a way in,
    and a developer who wants it back can set one variable.
    """
    settings = get_settings()
    application = FastAPI(
        title="Reticle",
        version="1.0.0",
        description="Step-by-step guides and standard operating procedures.",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    # ---- middleware ------------------------------------------------------
    #
    # READ THIS BEFORE REORDERING. `add_middleware` inserts at the front, so
    # **the last one added is the outermost**, and the list below therefore
    # reads inside-out. Getting this backwards is not cosmetic: a refusal issued
    # by an outer layer never reaches the inner ones, so putting the layers that
    # add the id, the log line and the security headers *inside* the layers that
    # reject leaves every 429 and 413 without any of them.
    #
    # The resulting chain, outermost first:
    #
    #   CORS  →  SecurityHeaders  →  RequestContext  →  UnhandledError  →
    #   SizeLimit  →  RateLimit  →  CSRF  →  the route
    #
    # Each position is load-bearing:
    #
    #   CORS outermost         a rejected preflight must still answer with the
    #                          CORS headers, or the browser reports a network
    #                          error instead of the real refusal.
    #   SecurityHeaders next   so *every* response carries them, including ones
    #                          produced by a middleware that never reaches a
    #                          route.
    #   RequestContext next    so every response has an id and every request is
    #                          logged - including the ones refused below it.
    #   UnhandledError then    inside those two, so a 500 it builds carries the
    #                          real id and the headers.
    #   SizeLimit then         refuses an over-long body before anything reads
    #                          it.
    #   RateLimit then         cheap, and before the body is parsed.
    #   CSRF innermost         it only guards routes.
    application.add_middleware(CsrfMiddleware)
    application.add_middleware(RateLimitMiddleware, settings=settings)
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=settings.max_request_bytes,
        # Headroom over the video cap for multipart framing and the file name.
        upload_max_bytes=settings.max_video_bytes + 5 * 1024 * 1024,
    )
    application.add_middleware(UnhandledErrorMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", CSRF_HEADER],
    )

    # Starlette types a handler as taking a bare ``Exception``; each of these
    # takes the class it is registered for, which is the only thing it can be
    # called with. Narrowing at the signature is worth more than matching the
    # declared type.
    application.add_exception_handler(errors.ApiError, handle_api_error)  # type: ignore[arg-type]
    application.add_exception_handler(RequestValidationError, handle_validation_error)  # type: ignore[arg-type]
    application.add_exception_handler(StarletteHTTPException, handle_http_exception)  # type: ignore[arg-type]

    for module in (
        auth,
        categories,
        discovery,
        export,
        guides,
        media,
        pages,
        system,
        telemetry,
        users,
    ):
        application.include_router(module.router)

    return application


async def handle_api_error(request: Request, exc: errors.ApiError) -> JSONResponse:
    return _failure(exc.status_code, exc.body())


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    failure = errors.validation_failed(_describe_validation(exc))
    return _failure(failure.status_code, failure.body())


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Whatever the framework itself raised, wearing the contract's envelope.

    FastAPI raises its own ``HTTPException`` for things no handler sees — an
    unparseable path parameter, a method the route does not accept — and its
    native body has a ``detail`` key that leaks the raw validation structure.
    A status this application has no code for is reported as a validation
    failure, which is what every such case has actually been.
    """
    code = STATUS_TO_CODE.get(exc.status_code, "validation_failed")
    return _failure(exc.status_code, errors.ApiError(code, str(exc.detail)).body())


def _size_words(cap: int) -> str:
    """Say a byte count the way the person reading the refusal thinks about it.

    Whole megabytes below one megabyte round to "0 MB", which reads as a server
    that accepts nothing — and small caps are exactly what a test or a locked
    down deployment sets.
    """
    if cap >= 1024 * 1024:
        return f"{cap // (1024 * 1024)} MB"
    if cap >= 1024:
        return f"{cap // 1024} KB"
    return f"{cap} bytes"


def _failure(status_code: int, body: dict) -> JSONResponse:
    """An error response carrying the id of the request that produced it.

    In the body as well as the header, because the header is invisible to
    somebody reading an error message on screen, and the whole point is that
    they can quote it in a report.
    """
    identifier = request_id.get()
    enriched = {**body, "requestId": identifier}
    return JSONResponse(
        status_code=status_code, content=enriched, headers={REQUEST_ID_HEADER: identifier}
    )


def _describe_validation(exc: RequestValidationError) -> str:
    """Turn pydantic's structured report into one human sentence.

    The contract gives errors a single ``message``, and echoing the raw input
    back would risk reflecting a submitted password into a response body.
    """
    parts = []
    for error in exc.errors()[:5]:
        location = ".".join(str(item) for item in error.get("loc", ()) if item != "body")
        parts.append(f"{location or 'request'}: {error.get('msg', 'is invalid')}")
    return "; ".join(parts) or "The request could not be understood."


def _dependant_requires_auth(dependant) -> bool:
    for sub_dependant in dependant.dependencies:
        if sub_dependant.call is get_session_row or _dependant_requires_auth(sub_dependant):
            return True
    return False


def _all_routes() -> list[object]:
    """Every route the application will actually serve, wrappers expanded.

    ``include_router`` does not copy a router's routes into ``app.routes``; it
    inserts one pathless wrapper holding the original router. Walking
    ``app.routes`` directly therefore sees a handful of endpoints and skips every
    wrapper as pathless — so the sweep below would report no holes because it was
    inspecting almost nothing. Expanding the wrappers is what makes the sweep an
    assertion about the application rather than about one list.
    """
    flattened: list[object] = []
    pending = list(app.routes)
    while pending:
        route = pending.pop()
        nested = getattr(route, "original_router", None)
        if nested is not None:
            pending.extend(nested.routes)
        else:
            flattened.append(route)
    return flattened


def unauthenticated_routes() -> list[str]:
    """Every route of any kind that no authentication dependency protects.

    Route-level authorisation is easy to forget and impossible to notice: the
    endpoint simply works for everybody. Enumerating the holes turns that into
    something a test can fail on.

    The sweep covers every route the application serves and measures them
    against one fixed allow-list, rather than filtering to the ``/api`` prefix
    and taking the exempt set from the caller. Both of those details mattered:
    the holes that actually appeared here were ``/docs``, ``/redoc`` and
    ``/openapi.json``, which carry no ``/api`` prefix and so could not have been
    caught by a filter that assumed one, and an allow-list a caller passes in is
    an allow-list the caller can widen to make the assertion pass.
    """
    unguarded = []
    for route in _all_routes():
        path = getattr(route, "path", None)
        if path is None or path in PUBLIC_PATHS:
            continue
        if not isinstance(route, APIRoute) or not _dependant_requires_auth(route.dependant):
            unguarded.append(path)
    return sorted(unguarded)


app = create_app()

"""The Reticle application: middleware, error translation and wiring.

Reticle is ZMB's self-hosted guide and wiki platform. The whole application
sits behind the login; only the health probe and the login endpoint itself are
reachable without a session, and :func:`unauthenticated_routes` exists so that
"only" can be asserted rather than assumed.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import db, errors, migrate
from .auth import SAFE_METHODS, DbDep, get_session_row
from .routers import auth, categories, guides, media, pages, search, tags, users
from .security import CSRF_COOKIE, CSRF_HEADER, constant_time_equals, prune_stale_rows
from .settings import get_settings

logger = logging.getLogger(__name__)

CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})

PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/login"})

UPLOAD_PATH = "/api/media"

MULTIPART_HEADROOM_BYTES = 1024 * 1024
"""Room for the multipart boundaries and the other form fields around a file."""

STATUS_TO_CODE = {401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "not_found"}


class RequestSizeLimitMiddleware:
    """Refuse an over-long body: from its declared length, and again as it arrives.

    Written against the raw ASGI interface rather than as a
    ``BaseHTTPMiddleware`` so that it decides before any part of the stack has a
    reason to buffer: what allocates the body is the endpoint reading it for
    validation, and on the login endpoint that allocation is performed on behalf
    of a caller who has not authenticated and never will. A 210 MB login attempt
    was held in memory in full and only then rejected as invalid.

    The declared length is only the cheap first check. A chunked request
    declares nothing, so the bytes are also counted as they are received and the
    request is abandoned at the first one over the limit.

    There are two limits and the larger is granted by route, not by content
    type. Only the upload endpoint has any business receiving megabytes, and it
    used to be enough to *label* a request multipart to be exempt everywhere —
    including on the login endpoint, which would then read the lot.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, max_upload_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.max_upload_bytes = max_upload_bytes

    def limit_for(self, scope: Scope) -> int:
        if scope["method"] == "POST" and scope["path"].rstrip("/") == UPLOAD_PATH:
            return self.max_upload_bytes
        return self.max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = self.limit_for(scope)
        declared = Headers(scope=scope).get("content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            await self._refuse(limit, scope, receive, send)
            return

        received = 0
        exceeded = False
        response_started = False

        async def counting_receive() -> Message:
            """Hand the body on until it runs over, then report the client as gone.

            Raising here would be the obvious thing, and it does not work: the
            layers in between run the body stream inside task groups, which
            turn the exception into something no handler recognises. A
            disconnect is a message every layer already knows how to stop on.
            """
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            """Drop whatever the application says about a body we cut short."""
            nonlocal response_started
            if exceeded and not response_started:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded or response_started:
                raise
        if exceeded and not response_started:
            await self._refuse(limit, scope, receive, send)

    @staticmethod
    async def _refuse(limit: int, scope: Scope, receive: Receive, send: Send) -> None:
        failure = errors.payload_too_large(too_large_message(limit))
        response = JSONResponse(status_code=failure.status_code, content=failure.body())
        await response(scope, receive, send)


def too_large_message(limit: int) -> str:
    megabytes = limit / (1024 * 1024)
    return f"Requests here must be at most {megabytes:.3g} MB."


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


API_CONTENT_SECURITY_POLICY = "default-src 'none'; frame-ancestors 'none'"

HSTS = "max-age=31536000"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Blanket hardening headers.

    The API returns JSON, media and PDFs, never a page, so it can afford the
    strictest possible policy: nothing embeds it, nothing sniffs it, no referrer
    leaves, and a response that somehow were rendered as a document could load
    and run nothing.

    ``no-store`` is the default because every response is somebody's
    authenticated view of the content; a shared instrument PC's back button
    should not be a way to read the previous user's drafts. Endpoints that are
    safe to cache, like media, say so themselves and are left alone.

    HSTS is sent whenever the session cookie is marked Secure, which is the
    operator's statement that this deployment is HTTPS-only.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("Content-Security-Policy", API_CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Cache-Control", "no-store")
        if get_settings().cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Refuse to serve from a database whose schema is not the one this code expects.

    The schema is owned by the migrations, and applying them is a deliberate
    step — ``python -m app.migrate`` — rather than something each worker does on
    its way up. Starting anyway against an old schema would not fail here; it
    would fail later, one request at a time, on whichever column is missing.

    The same moment is used to clear out expired sessions and stale throttle
    rows, so the tables are trimmed on every restart even on a server nobody
    signs in to for a month.
    """
    migrate.assert_current(db.engine)
    with db.SessionLocal() as session:
        prune_stale_rows(session)
        session.commit()
    yield


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
        description="Guides and wiki pages for the Center for Microscopy and Image Analysis, University of Zurich.",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CsrfMiddleware)
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=settings.max_request_bytes,
        max_upload_bytes=max(settings.max_upload_bytes, settings.max_video_bytes) + MULTIPART_HEADROOM_BYTES,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", CSRF_HEADER],
    )

    @application.exception_handler(errors.ApiError)
    async def handle_api_error(request: Request, exc: errors.ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body())

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        failure = errors.validation_failed(_describe_validation(exc))
        return JSONResponse(status_code=failure.status_code, content=failure.body())

    @application.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = STATUS_TO_CODE.get(exc.status_code)
        if code is None:
            failure = errors.ApiError("validation_failed", str(exc.detail))
            return JSONResponse(status_code=exc.status_code, content=failure.body())
        failure = errors.ApiError(code, str(exc.detail))
        return JSONResponse(status_code=exc.status_code, content=failure.body())

    @application.get("/api/health", tags=["health"])
    def health(session: DbDep) -> JSONResponse:
        """Liveness, including the one dependency that can be down: the database.

        The failure body says nothing about why. This endpoint is reachable
        without a session, and a driver error message is a description of the
        server's insides.
        """
        try:
            session.execute(text("SELECT 1"))
        except Exception:
            logger.exception("Health check could not reach the database.")
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return JSONResponse(content={"status": "ok"})

    for module in (auth, categories, guides, media, pages, search, tags, users):
        application.include_router(module.router)

    return application


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


def _leaf_routes(routes: Iterable[Any]) -> Iterator[tuple[str, Any]]:
    """Every concrete route under the application, however it was attached.

    Included routers are not flattened into ``app.routes`` by current FastAPI;
    each appears there as one opaque wrapper holding the router it came from.
    An earlier version of this sweep looked for a ``path`` attribute, found none
    on the wrappers, and skipped them — which silently reduced "every route is
    authenticated" to "the health probe is on the allow-list". So the wrappers
    are opened here, and anything that is neither a route nor a wrapper is
    yielded as it stands for the caller to refuse.
    """
    for route in routes:
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from _leaf_routes(nested.routes)
        else:
            yield getattr(route, "path", repr(route)), route


def inspected_routes(application: FastAPI | None = None) -> list[str]:
    """The paths the authentication sweep looks at; exposed so a test can prove
    the sweep is not vacuous."""
    target = application if application is not None else app
    return sorted({path for path, _ in _leaf_routes(target.routes)})


def unauthenticated_routes(application: FastAPI | None = None) -> list[str]:
    """Every route of any kind that no authentication dependency protects.

    Route-level authorisation is easy to forget and impossible to notice: the
    endpoint simply works for everybody. Enumerating the holes turns that into
    something a test can fail on.

    The sweep covers every route and measures them against one fixed
    allow-list, rather than filtering to the ``/api`` prefix and taking the
    exempt set from the caller. Both of those details mattered: the holes that
    actually appeared here were ``/docs``, ``/redoc`` and ``/openapi.json``,
    which carry no ``/api`` prefix and so could not have been caught by a filter
    that assumed one, and an allow-list a caller passes in is an allow-list the
    caller can widen to make the assertion pass.

    It fails closed. A route object this function does not recognise is reported
    as unguarded rather than passed over, so the next change to how the
    framework stores routes shows up as a failing test instead of a blind spot.
    """
    target = application if application is not None else app
    unguarded = []
    for path, route in _leaf_routes(target.routes):
        if path in PUBLIC_PATHS:
            continue
        if not isinstance(route, APIRoute) or not _dependant_requires_auth(route.dependant):
            unguarded.append(path)
    return sorted(unguarded)


app = create_app()

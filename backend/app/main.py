"""The Reticle application: middleware, error translation and wiring.

Reticle is ZMB's self-hosted step-by-step guide platform. The whole application
sits behind the login; only the health probe and the login endpoint itself are
reachable without a session, and :func:`unauthenticated_routes` exists so that
"only" can be asserted rather than assumed.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT
"""

from __future__ import annotations

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
from starlette.types import ASGIApp, Receive, Scope, Send

from . import errors
from .auth import SAFE_METHODS, get_session_row
from .db import init_db
from .routers import auth, categories, discovery, guides, media, pages, users
from .security import CSRF_COOKIE, CSRF_HEADER, constant_time_equals
from .settings import get_settings

CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})

PUBLIC_PATHS = frozenset({"/api/health", "/api/auth/login"})

MULTIPART_PREFIX = "multipart/form-data"

STATUS_TO_CODE = {401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "not_found"}


class RequestSizeLimitMiddleware:
    """Refuse an over-long body from its declared length, before anything reads it.

    Written against the raw ASGI interface rather than as a
    ``BaseHTTPMiddleware`` so that it decides before any part of the stack has a
    reason to buffer: what allocates the body is the endpoint reading it for
    validation, and on the login endpoint that allocation is performed on behalf
    of a caller who has not authenticated and never will. A 210 MB login attempt
    was held in memory in full and only then rejected as invalid.

    Multipart requests are exempt because uploads legitimately run to tens of
    megabytes and ``media`` already streams them against its own, larger cap
    instead of trusting the declared length.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._is_too_large(Headers(scope=scope)):
            failure = errors.payload_too_large(
                f"Requests must be at most {self.max_bytes // (1024 * 1024)} MB."
            )
            response = JSONResponse(status_code=failure.status_code, content=failure.body())
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _is_too_large(self, headers: Headers) -> bool:
        if headers.get("content-type", "").startswith(MULTIPART_PREFIX):
            return False
        declared = headers.get("content-length")
        return bool(declared and declared.isdigit() and int(declared) > self.max_bytes)


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
    """Create any table that does not exist yet.

    This makes ``uvicorn app.main:app`` work on a fresh checkout instead of
    failing on the first query. ``create_all`` only adds what is absent — it
    never alters or drops — so it cannot quietly stand in for a migration when
    the schema later changes.
    """
    init_db()
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
        description="Step-by-step guides for the Center for Microscopy and Image Analysis, University of Zurich.",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CsrfMiddleware)
    application.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
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
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (auth, categories, discovery, guides, media, pages, users):
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


def unauthenticated_routes() -> list[str]:
    """Every route of any kind that no authentication dependency protects.

    Route-level authorisation is easy to forget and impossible to notice: the
    endpoint simply works for everybody. Enumerating the holes turns that into
    something a test can fail on.

    The sweep covers all of ``app.routes`` and measures them against one fixed
    allow-list, rather than filtering to the ``/api`` prefix and taking the
    exempt set from the caller. Both of those details mattered: the holes that
    actually appeared here were ``/docs``, ``/redoc`` and ``/openapi.json``,
    which carry no ``/api`` prefix and so could not have been caught by a filter
    that assumed one, and an allow-list a caller passes in is an allow-list the
    caller can widen to make the assertion pass.
    """
    unguarded = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None or path in PUBLIC_PATHS:
            continue
        if not isinstance(route, APIRoute) or not _dependant_requires_auth(route.dependant):
            unguarded.append(path)
    return sorted(unguarded)


app = create_app()

"""The Reticle application: middleware, error translation and wiring.

Reticle is ZMB's self-hosted step-by-step guide platform. The whole application
sits behind the login; only the health probe and the login endpoint itself are
reachable without a session, and :func:`unauthenticated_api_routes` exists so
that "only" can be asserted rather than assumed.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

from . import errors
from .auth import SAFE_METHODS, get_session_row
from .db import init_db
from .routers import auth, categories, guides, media, users
from .security import CSRF_COOKIE, CSRF_HEADER, constant_time_equals
from .settings import get_settings

CSRF_EXEMPT_PATHS = frozenset({"/api/auth/login"})

STATUS_TO_CODE = {401: "not_authenticated", 403: "forbidden", 404: "not_found", 405: "not_found"}


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
    settings = get_settings()
    application = FastAPI(
        title="Reticle",
        version="1.0.0",
        description="Step-by-step guides for the Center for Microscopy and Image Analysis, University of Zurich.",
        lifespan=lifespan,
    )

    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CsrfMiddleware)
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

    for module in (auth, categories, guides, media, users):
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


def unauthenticated_api_routes(exempt: Iterable[str] = ()) -> list[str]:
    """Every ``/api`` route that no authentication dependency protects.

    Route-level authorisation is easy to forget and impossible to notice: the
    endpoint simply works for everybody. Enumerating the holes turns that into
    something a test can fail on.
    """
    exempt_paths = set(exempt)
    unguarded = []
    for route in app.routes:
        if not isinstance(route, (APIRoute, Route)) or not route.path.startswith("/api"):
            continue
        if route.path in exempt_paths:
            continue
        if not isinstance(route, APIRoute) or not _dependant_requires_auth(route.dependant):
            unguarded.append(route.path)
    return sorted(unguarded)


app = create_app()

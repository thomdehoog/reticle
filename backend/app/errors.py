"""Every way a request can fail, and the exact shape the caller is told about it.

When something goes wrong the browser gets one thing back, always:
``{"error": {"code": …, "message": …}, "requestId": …}``. The *code* is a short
word a program can branch on — ``not_found``, ``conflict`` — and the *message*
is a sentence a person reads on screen. The list of codes is the table below,
and it is the whole list; there is no other kind of error.

This is its own file so that the codes and the HTTP status each one means are
decided in one place instead of being invented at each ``raise``. Two endpoints
answering the same failure with different words is how a frontend ends up with a
special case per route.

The non-obvious part: a lot of failures are not raised by this application at
all. FastAPI refuses a malformed body, Starlette refuses an unknown path, and
both have their own response shapes. ``main`` catches those and rewrites them
into the envelope above, which is why a client never has to recognise anybody
else's format. The ``requestId`` is added there too — see ``main._failure``.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

from typing import Any

STATUS_FOR_CODE = {
    "invalid_credentials": 401,
    "not_authenticated": 401,
    "forbidden": 403,
    "not_found": 404,
    "conflict": 409,
    "payload_too_large": 413,
    "validation_failed": 422,
    "rate_limited": 429,
    # Nothing raises this deliberately. It is what the catch-all handler in
    # `main` returns for an exception nobody anticipated, so that a caller gets
    # the documented error envelope and a request id instead of an empty body.
    "internal_error": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        if code not in STATUS_FOR_CODE:
            raise ValueError(f"unknown error code {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status_code(self) -> int:
        return STATUS_FOR_CODE[self.code]

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}}


def invalid_credentials(message: str = "Email or password is incorrect.") -> ApiError:
    return ApiError("invalid_credentials", message)


def not_authenticated(message: str = "Sign in to continue.") -> ApiError:
    return ApiError("not_authenticated", message)


def forbidden(message: str = "Your role does not allow this.") -> ApiError:
    return ApiError("forbidden", message)


def not_found(message: str = "Not found.") -> ApiError:
    return ApiError("not_found", message)


def conflict(message: str) -> ApiError:
    return ApiError("conflict", message)


def payload_too_large(message: str) -> ApiError:
    return ApiError("payload_too_large", message)


def validation_failed(message: str) -> ApiError:
    return ApiError("validation_failed", message)


def rate_limited(message: str = "Too many attempts. Try again later.") -> ApiError:
    return ApiError("rate_limited", message)

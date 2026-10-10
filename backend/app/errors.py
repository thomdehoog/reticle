"""The single error vocabulary the API contract defines.

Every failure leaves the application as an :class:`ApiError`, so there is one
place that decides both the machine code and the HTTP status. Handlers in
``main`` translate framework-raised failures into the same envelope, which is
why a client never has to special-case FastAPI's native validation shape.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
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


# ------------------------------------------------- validation, in plain words

_REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})

_FIELD_LABELS = {
    "timeRequiredMinMinutes": "Minimum time required",
    "timeRequiredMaxMinutes": "Maximum time required",
    "categoryId": "Category",
    "parentId": "Parent category",
    "heroMediaId": "Hero image",
    "heroAlt": "Hero image description",
    "alt": "Image description",
    "orderIndex": "Position",
    "isLanding": "Landing page",
    "isHidden": "Hidden",
    "isActive": "Active",
    "q": "Search term",
}
"""Names that do not read as words once split. Everything else is humanised
mechanically, so a field added tomorrow gets a passable label without anyone
remembering this table exists."""

_WIRE_NAMES = frozenset({"expectedUpdatedAt"})
"""Fields no person fills in. Only a client program can get the concurrency
token wrong, and whoever is debugging that client needs the name as it is
spelt on the wire, not a paraphrase of it."""

_WORD_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|_")

_PLAIN_BY_TYPE = {
    "missing": "is required",
    "string_type": "must be text",
    "string_pattern_mismatch": "contains characters that are not allowed here",
    "int_type": "must be a whole number",
    "int_parsing": "must be a whole number",
    "int_from_float": "must be a whole number",
    "float_type": "must be a number",
    "float_parsing": "must be a number",
    "finite_number": "must be an ordinary number",
    "bool_type": "must be true or false",
    "bool_parsing": "must be true or false",
    "list_type": "must be a list",
    "dict_type": "must be an object",
    "model_type": "must be an object",
    "model_attributes_type": "must be an object",
    "datetime_type": "must be a date and time",
    "datetime_parsing": "must be a date and time",
    "datetime_from_date_parsing": "must be a date and time",
    "json_invalid": "is not valid JSON",
}

_BOUND_BY_TYPE = {
    "greater_than_equal": ("ge", "must be at least {}"),
    "greater_than": ("gt", "must be more than {}"),
    "less_than_equal": ("le", "must be at most {}"),
    "less_than": ("lt", "must be less than {}"),
}


def _plural(count: Any, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _field_label(name: str) -> str:
    if name in _FIELD_LABELS:
        return _FIELD_LABELS[name]
    if name in _WIRE_NAMES:
        return name
    words = [word for word in _WORD_BOUNDARY.split(name) if word]
    if len(words) > 1 and words[-1].lower() == "id":
        words.pop()
    return " ".join(words).lower() or name


def _singular(label: str) -> str:
    return label[:-1] if label.endswith("s") and not label.endswith("ss") else label


def _location_label(location: Sequence[Any]) -> str:
    """Where in the document, as an author would say it: "Step 2, bullet 3, text".

    A list index becomes a one-based ordinal on the singular of the list's own
    name, because "steps.1.bullets.2.text" is an address in a data structure
    and the person reading this is looking at a second step and a third bullet.
    """
    items = list(location)
    if items and items[0] in _REQUEST_PARTS:
        items = items[1:]
    parts: list[str] = []
    for item in items:
        if isinstance(item, int) and parts:
            parts[-1] = f"{_singular(parts[-1])} {item + 1}"
        else:
            parts.append(_field_label(str(item)))
    label = ", ".join(parts)
    if parts and parts[0] in _WIRE_NAMES:
        return label
    return label[:1].upper() + label[1:]


def _problem(error: Mapping[str, Any]) -> str:
    """What is wrong, phrased to follow a field name; never echoes the input."""
    kind = str(error.get("type", ""))
    context = error.get("ctx") or {}
    message = str(error.get("msg") or "")

    if kind in _PLAIN_BY_TYPE:
        return _PLAIN_BY_TYPE[kind]
    if kind in _BOUND_BY_TYPE:
        key, template = _BOUND_BY_TYPE[kind]
        return template.format(context.get(key))
    if kind == "string_too_long":
        return f"must be at most {_plural(context.get('max_length'), 'character')}"
    if kind == "string_too_short":
        minimum = context.get("min_length")
        return "must not be empty" if minimum == 1 else f"must be at least {_plural(minimum, 'character')}"
    if kind == "too_long":
        return f"must have at most {_plural(context.get('max_length'), 'item')}"
    if kind == "too_short":
        return f"must have at least {_plural(context.get('min_length'), 'item')}"
    if kind == "literal_error":
        return f"must be {context.get('expected')}"
    if kind == "value_error":
        # Our own validators raise ValueError with a sentence; pydantic files
        # it under a "Value error, " prefix that means nothing to an author.
        text = message.removeprefix("Value error, ").strip()
        if text.startswith("value is not a valid email address"):
            return "must be a valid email address"
        return text or "is not valid"
    if message.startswith("Input should "):
        return "must " + message.removeprefix("Input should ")
    return "is not valid"


def describe_validation(problems: Sequence[Mapping[str, Any]]) -> str:
    """Turn pydantic's structured report into sentences an author can act on.

    The contract gives errors a single ``message`` and the editors show it as
    it stands, to someone writing a microscopy protocol rather than a program.
    So the request-part prefix, the dotted path and pydantic's own phrasing
    ("Value error, …", "String should have at most …") are all replaced:
    ``Title: must be at most 240 characters.`` for a field, and the validator's
    own sentence when the problem is about the document as a whole.

    Nothing here repeats what was submitted. Echoing the raw input back would
    risk reflecting a password into a response body.
    """
    sentences = []
    for error in problems[:5]:
        label = _location_label(error.get("loc", ()))
        problem = _problem(error).rstrip(".")
        sentence = f"{label}: {problem}" if label else problem[:1].upper() + problem[1:]
        sentences.append(f"{sentence}.")
    return " ".join(sentences) or "The request could not be understood."

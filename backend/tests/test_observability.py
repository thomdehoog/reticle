"""Logs, and the two ways logging goes wrong.

The first is that there are none, which is what this module was written to fix.
The second is worse and is what most of this file guards: logs that capture the
things they were never supposed to see. Reticle's requests carry passwords on
the login endpoint, session cookies on every endpoint, and search terms that are
themselves institute business. A log that records those turns every future
reader of a log file — an operator, a backup, a support ticket — into somebody
who can sign in.

So the assertions here are mostly negative, and they are the point.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
import logging

import pytest

from app.main import _redacted
from app.observability import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    configure_logging,
    request_id,
)


@pytest.fixture
def captured(monkeypatch):
    """Every log line emitted during the block, parsed back from JSON."""
    lines: list[dict] = []

    class Collector(logging.Handler):
        def emit(self, record):
            lines.append(json.loads(JsonFormatter().format(record)))

    # Apply the real production configuration first, then swap only the
    # handler. Building a bare root logger here instead would test a setup
    # nothing runs — and would miss exactly the leaks that configuration
    # exists to prevent, since silencing chatty libraries is part of it.
    configure_logging()

    root = logging.getLogger()
    original, original_level = root.handlers, root.level
    root.handlers = [Collector()]
    root.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        root.handlers, root.level = original, original_level


# --- what must never appear ------------------------------------------------


def test_a_password_submitted_to_the_login_endpoint_is_not_logged(anon, make_user, captured):
    make_user("logged@zmb.uzh.ch")

    anon.login("logged@zmb.uzh.ch", "correct-horse-battery-staple")

    written = json.dumps(captured)
    assert "correct-horse-battery-staple" not in written


def test_the_session_cookie_is_not_logged(author, captured):
    author.get("/api/auth/me")

    written = json.dumps(captured)
    assert author.cookies.get("reticle_session") not in written


def test_a_search_term_is_not_logged(author, captured):
    author.get("/api/search", params={"q": "unpublished cryo results"})

    written = json.dumps(captured)
    assert "unpublished cryo results" not in written
    assert "cryo" not in written


def test_the_path_is_the_route_template_not_the_resolved_identifier(author, category, captured):
    """Logging the resolved path writes an identifier into every line and makes
    the logs impossible to aggregate — each guide becomes its own distinct key."""
    from .conftest import create_guide

    guide = create_guide(author, category.id, "Logged Guide")
    captured.clear()
    author.get(f"/api/guides/{guide['id']}")

    paths = [line.get("path") for line in captured if "path" in line]
    assert paths, "no request was logged at all"
    assert guide["id"] not in json.dumps(paths)


# --- what must appear ------------------------------------------------------


def test_a_request_is_logged_with_its_outcome_and_duration(author, captured):
    author.get("/api/auth/me")

    entry = next(line for line in captured if line.get("logger") == "reticle.request")
    assert entry["method"] == "GET"
    assert entry["path"] == "/api/auth/me"
    assert entry["status"] == 200
    assert isinstance(entry["durationMs"], float)
    assert entry["requestId"] != "-"


def test_the_response_carries_the_id_that_the_log_line_carries(author, captured):
    response = author.get("/api/auth/me")

    entry = next(line for line in captured if line.get("logger") == "reticle.request")
    assert response.headers[REQUEST_ID_HEADER] == entry["requestId"]


def test_an_error_response_quotes_its_own_request_id(anon):
    """The user reporting a failure reads the body, not the headers. Without the
    id in the body, "it broke this morning" stays unfindable."""
    response = anon.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["requestId"] == response.headers[REQUEST_ID_HEADER]


def test_two_requests_do_not_share_an_id(author):
    first = author.get("/api/auth/me").headers[REQUEST_ID_HEADER]
    second = author.get("/api/auth/me").headers[REQUEST_ID_HEADER]

    assert first != second


# --- the id coming in from a proxy ----------------------------------------


def test_an_id_from_an_upstream_tracer_is_kept(author):
    """A reverse proxy that is already tracing has an id; adopting it is what
    joins Reticle's logs to the ones in front of it."""
    response = author.get("/api/auth/me", headers={REQUEST_ID_HEADER: "abcdef0123456789"})

    assert response.headers[REQUEST_ID_HEADER] == "abcdef0123456789"


@pytest.mark.parametrize(
    "hostile",
    [
        'evil"\n{"level":"INFO","message":"admin logged in"',  # forged log entry
        "short",  # too short to be an id
        "x" * 500,  # unbounded
        "has spaces and : colons",
    ],
)
def test_an_implausible_id_is_replaced_rather_than_echoed(author, hostile):
    """The id is written into log files, so accepting arbitrary text lets a
    caller inject newlines and forge entries around their own request."""
    response = author.get("/api/auth/me", headers={REQUEST_ID_HEADER: hostile})

    assert response.headers[REQUEST_ID_HEADER] != hostile
    assert "\n" not in response.headers[REQUEST_ID_HEADER]


# --- the formatter ---------------------------------------------------------


def test_every_line_is_one_parseable_json_object():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)

    assert json.loads(JsonFormatter().format(record))["message"] == "hello"


def test_extra_fields_reach_the_output():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    record.guideId = "01H"

    assert json.loads(JsonFormatter().format(record))["guideId"] == "01H"


def test_a_value_that_cannot_be_serialised_does_not_break_the_request():
    """A logging call must never be the thing that takes down the request it
    was describing."""
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    record.thing = object()

    assert json.loads(JsonFormatter().format(record))["thing"].startswith("<object")


def test_the_current_request_id_is_stamped_on_unrelated_log_lines():
    """The reason for a ContextVar: a warning written deep inside a handler has
    to be joinable to the request that caused it."""
    token = request_id.set("deadbeefcafe")
    try:
        record = logging.LogRecord("t", logging.WARNING, __file__, 1, "m", None, None)
        assert json.loads(JsonFormatter().format(record))["requestId"] == "deadbeefcafe"
    finally:
        request_id.reset(token)


def test_configuring_twice_does_not_double_every_line():
    """uvicorn installs its own handler; leaving both attached prints each line
    twice and makes the JSON stream invalid for anything parsing it."""
    configure_logging()
    configure_logging()

    assert len(logging.getLogger().handlers) == 1


# --- the startup line ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite:///./reticle.db", "sqlite:///./reticle.db"),
        (
            "postgresql+psycopg://reticle:hunter2@db.internal/reticle",
            "postgresql+psycopg://reticle:***@db.internal/reticle",
        ),
        ("postgresql://user:p%40ss@host:5432/db", "postgresql://user:***@host:5432/db"),
    ],
)
def test_the_startup_line_never_prints_the_database_password(url, expected):
    """Startup logs are the ones people paste into tickets."""
    assert _redacted(url) == expected


# --- crash reports from the browser ----------------------------------------


def test_a_browser_crash_reaches_the_log(author, captured):
    """The whole point: a rendering bug used to reach a developer as "it did
    not work this morning", if at all."""
    response = author.post(
        "/api/client-errors",
        json={
            "message": "annotation has no shape",
            "componentStack": "at StepGallery",
            "url": "/g/x",
        },
    )

    assert response.status_code == 204
    entry = next(line for line in captured if line.get("logger") == "reticle.client")
    assert entry["clientMessage"] == "annotation has no shape"
    assert entry["level"] == "ERROR"
    assert entry["userId"]


def test_a_crash_report_cannot_forge_surrounding_log_entries(author, captured):
    """The risk this endpoint carries. It writes caller-supplied text to a log
    file, and a newline in that text reads back as a separate record — so an
    account could manufacture entries saying whatever it liked."""
    author.post(
        "/api/client-errors",
        json={
            "message": 'boom\n{"level":"INFO","logger":"reticle.request","message":"admin logged in"}',
            "componentStack": "line one\nline two",
        },
    )

    entry = next(line for line in captured if line.get("logger") == "reticle.client")
    assert "\n" not in entry["clientMessage"]
    assert "\n" not in entry["componentStack"]
    assert "admin logged in" in entry["clientMessage"]  # kept, but as one field


def test_an_oversized_report_is_refused_rather_than_written(author):
    """Otherwise the endpoint is a way to fill a disk one request at a time."""
    response = author.post(
        "/api/client-errors",
        json={"message": "x" * 5000, "componentStack": "", "url": ""},
    )

    assert response.status_code == 422


def test_reporting_a_crash_is_refused_without_a_session(anon):
    """403 rather than 401: the CSRF check runs as middleware, ahead of routing,
    so an anonymous POST is stopped before the authentication dependency is
    reached. Either way it does not reach the log, which is what matters — an
    unauthenticated write into a log file is a way to fill a disk from
    outside."""
    response = anon.post("/api/client-errors", json={"message": "boom"})

    assert response.status_code in (401, 403)
    assert response.status_code != 204

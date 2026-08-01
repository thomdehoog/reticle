"""Guarding the two ways a migration loses records without saying anything.

The first is paging. A loop that stops one page early takes the last hundred
guides of a corpus with it, and every count downstream agrees with itself
because both sides were derived from the short list.

The second is a transient failure treated as an empty result. A facility's
network drops a connection now and then, and a client that answers "nothing
here" to a timeout produces a migration that reconciles perfectly against the
half it managed to read.

Nothing here touches the network: the opener is replaced, which is also how the
retry timing is asserted without the suite sleeping through it.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from app.importer.client import PAGE_SIZE, DozukiClient, MigrationError


class FakeResponse:
    def __init__(self, payload: bytes, content_type: str = "application/json") -> None:
        self._buffer = BytesIO(payload)
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    """Answers with a scripted sequence, and records what was asked for."""

    def __init__(self, responses: list) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []
        self.headers: list[dict] = []

    def __call__(self, request, timeout=None):
        self.urls.append(request.full_url)
        self.headers.append(dict(request.headers))
        if not self._responses:
            raise AssertionError(f"No scripted response for {request.full_url}")
        answer = self._responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _json_response(value) -> FakeResponse:
    return FakeResponse(json.dumps(value).encode("utf-8"))


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://example.test", code, "boom", {}, None)


def _client(responses, **kwargs) -> tuple[DozukiClient, FakeOpener, list]:
    slept: list = []
    opener = FakeOpener(responses)
    client = DozukiClient(
        "https://example.test",
        opener=opener,
        sleep=slept.append,
        **kwargs,
    )
    return client, opener, slept


def test_a_full_page_is_followed_by_another_request():
    """Stopping on a full page would take the tail of the corpus with it."""
    first = [{"guideid": index} for index in range(PAGE_SIZE)]
    second = [{"guideid": 9001}]
    client, opener, _ = _client([_json_response(first), _json_response(second)])

    guides = list(client.iter_guides())

    assert len(guides) == PAGE_SIZE + 1
    assert f"offset={PAGE_SIZE}" in opener.urls[1]


def test_a_short_page_ends_the_walk():
    client, opener, _ = _client([_json_response([{"guideid": 1}])])

    assert len(list(client.iter_guides())) == 1
    assert len(opener.urls) == 1


def test_an_empty_catalogue_is_not_an_error():
    client, _, _ = _client([_json_response([])])
    assert list(client.iter_guides()) == []


def test_private_guides_are_only_asked_for_when_wanted():
    client, opener, _ = _client([_json_response([]), _json_response([])])

    list(client.iter_guides())
    assert "includePrivate" not in opener.urls[0]

    list(client.iter_guides(include_private=True))
    assert "includePrivate=true" in opener.urls[1]


def test_a_token_is_sent_only_when_there_is_one():
    client, opener, _ = _client([_json_response([])], token="secret")
    list(client.iter_guides())
    assert opener.headers[0].get("Authorization") == "api secret"

    plain, plain_opener, _ = _client([_json_response([])])
    list(plain.iter_guides())
    assert "Authorization" not in plain_opener.headers[0]


def test_a_transient_failure_is_retried_with_a_widening_delay():
    client, opener, slept = _client(
        [_http_error(503), _http_error(503), _json_response({"guideid": 1})]
    )

    assert client.get_guide(1) == {"guideid": 1}
    assert len(opener.urls) == 3
    assert slept == [2, 4]


def test_a_timeout_is_retried_rather_than_read_as_an_empty_result():
    client, opener, _ = _client([TimeoutError("slow"), _json_response({"guideid": 1})])
    assert client.get_guide(1) == {"guideid": 1}
    assert len(opener.urls) == 2


def test_giving_up_raises_rather_than_returning_nothing():
    client, _, slept = _client([_http_error(503)] * 5)

    with pytest.raises(MigrationError, match="Gave up"):
        client.get_guide(1)
    assert slept == [2, 4, 8, 16]


def test_a_permanent_failure_is_not_retried():
    """Retrying a 404 four times only delays telling somebody about it."""
    client, opener, slept = _client([_http_error(404)])

    with pytest.raises(MigrationError, match="404"):
        client.get_guide(1)
    assert len(opener.urls) == 1
    assert slept == []


def test_a_response_that_is_not_json_is_a_failure_not_a_silent_skip():
    client, _, _ = _client([FakeResponse(b"<html>maintenance</html>", "text/html")])

    with pytest.raises(MigrationError, match="did not return JSON"):
        client.get_guide(1)


def test_a_listing_that_is_not_a_list_stops_the_walk_loudly():
    client, _, _ = _client([_json_response({"error": "nope"})])

    with pytest.raises(MigrationError, match="not a list"):
        list(client.iter_guides())


def test_a_wiki_title_is_escaped_into_the_path():
    client, opener, _ = _client([_json_response({"title": "Light Microscopy"})])

    client.get_wiki("CATEGORY", "Light Microscopy/Confocal")

    assert "Light%20Microscopy%2FConfocal" in opener.urls[0]


def test_downloading_returns_the_bytes_and_the_declared_type():
    client, _, _ = _client([FakeResponse(b"\x89PNG...", "image/png")])

    fetched = client.download("https://example.test/one.png")

    assert fetched.payload == b"\x89PNG..."
    assert fetched.content_type == "image/png"
    assert fetched.url == "https://example.test/one.png"


def test_every_request_identifies_itself():
    """An operator watching their own logs should be able to see what this is."""
    client, opener, _ = _client([_json_response([])])
    list(client.iter_guides())
    assert "Reticle-Migration" in opener.headers[0].get("User-agent", "")

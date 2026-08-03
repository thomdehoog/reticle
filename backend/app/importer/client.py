"""Reading the vendor API, and fetching the files it points at.

Built on the standard library rather than on ``httpx`` so that the migration
tool adds no runtime dependency to the server, and so it runs on the ZMB
workstations, where AppLocker blocks executables under user-writable paths and
installing a package is not a five-second decision.

The client is deliberately dull: page through a list, fetch a document, download
a file, retry a transient failure with a widening delay, and give up loudly on
anything else. It has one job that matters — it must not silently return a short
list, because the reconciliation step downstream compares counts and a quietly
truncated page would make both sides agree on the wrong number.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

USER_AGENT = "Reticle-Migration/1.0 (ZMB, University of Zurich)"

PAGE_SIZE = 200
"""The largest page the API serves. Fewer requests, and fewer chances to lose one."""

RETRY_DELAYS_SECONDS = (2, 4, 8, 16)

TRANSIENT_STATUSES = frozenset({429, 500, 502, 503, 504})


class MigrationError(RuntimeError):
    """A failure that must stop the run rather than be worked around."""


ALLOWED_SCHEMES = frozenset({"http", "https"})


def _refuse_unless_http(url: str) -> None:
    """Refuse anything that is not an HTTP(S) fetch.

    ``urlopen`` handles ``file://`` as readily as ``https://``, and not every
    URL that reaches here is one the operator typed: image and video addresses
    come out of the source system's own payloads. A migration source that
    returned ``file:///etc/passwd`` as an image URL would have had it fetched,
    stored as media and served back through Reticle - a local file read
    triggered by a remote document, which is the shape of the bug worth
    preventing rather than reasoning about.

    ``ftp://`` and the rest go the same way. Nothing legitimate here needs
    them, so the list is what is allowed rather than what is denied.
    """
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise MigrationError(
            f"Refusing to fetch {url!r}: only http and https are allowed, not {scheme or 'a relative URL'!r}."
        )


@dataclass
class FetchedFile:
    payload: bytes
    content_type: str
    url: str


class DozukiClient:
    """A read-only client for the vendor's public API.

    Authentication is optional. The public catalogue needs none, which is what
    makes the migration a one-command job; a token is only required to include
    private guides, and the tool says so rather than failing obscurely when a
    private guide is skipped.
    """

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        timeout_seconds: float = 30.0,
        sleep=time.sleep,
        opener=None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        self._opener = opener or urllib.request.urlopen

    # -- plumbing ---------------------------------------------------------

    def _request(self, url: str) -> tuple[bytes, str]:
        _refuse_unless_http(url)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"api {self.token}"

        last_error: Exception | None = None
        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            request = urllib.request.Request(url, headers=headers)
            try:
                with self._opener(request, timeout=self.timeout_seconds) as response:
                    return response.read(), response.headers.get("Content-Type", "")
            except urllib.error.HTTPError as error:
                if error.code not in TRANSIENT_STATUSES:
                    raise MigrationError(f"{error.code} from {url}: {error.reason}") from error
                last_error = error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error

            if attempt < len(RETRY_DELAYS_SECONDS):
                self._sleep(RETRY_DELAYS_SECONDS[attempt])

        raise MigrationError(
            f"Gave up on {url} after {len(RETRY_DELAYS_SECONDS)} retries: {last_error}"
        )

    def get_json(self, path: str, **params: Any) -> Any:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        payload, _ = self._request(url)
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise MigrationError(f"{url} did not return JSON: {error}") from error

    def download(self, url: str) -> FetchedFile:
        payload, content_type = self._request(url)
        return FetchedFile(payload=payload, content_type=content_type, url=url)

    # -- catalogue --------------------------------------------------------

    def _iter_listing(self, path: str, **params: Any) -> Iterator[dict[str, Any]]:
        """Page a listing endpoint until it is exhausted.

        Two things this must not do, both measured against the live site rather
        than reasoned about:

        **It must not stop on a short page.** The vendor takes a slice of the
        catalogue and filters it afterwards, so a page of 200 comes back holding
        176 and that says nothing at all about whether more exist. Six of the
        eight pages of ZMB's catalogue are short. Stopping at the first one
        fetched 47 guides of 257 and reported success — silently, because the
        reconciliation counts both the raw payload and the mapped document from
        the same truncated listing, so the two agreed with each other about a
        corpus that was 18% of the real one.

        **It must not advance by what arrived.** The offset indexes the list
        before that filtering, so it moves by the size asked for, never by the
        size received.

        The end is therefore an empty page, which is the only signal the API
        gives. That is exact unless a whole 200-wide window is filtered away
        while later windows still hold guides; nothing like it appears in ZMB's
        catalogue, where 43 of 300 slots are filtered and no page is empty
        before the last.
        """
        offset = 0
        while True:
            batch = self.get_json(path, limit=PAGE_SIZE, offset=offset, **params)
            if not isinstance(batch, list):
                raise MigrationError(f"Listing {path} at offset {offset} was not a list.")
            if not batch:
                return
            for item in batch:
                if isinstance(item, dict):
                    yield item
            offset += PAGE_SIZE

    def iter_guides(self, include_private: bool = False) -> Iterator[dict[str, Any]]:
        yield from self._iter_listing(
            "/api/2.0/guides",
            includePrivate="true" if include_private else None,
        )

    def get_guide(self, guide_id: str | int) -> dict[str, Any]:
        payload = self.get_json(f"/api/2.0/guides/{guide_id}")
        if not isinstance(payload, dict):
            raise MigrationError(f"Guide {guide_id} was not an object.")
        return payload

    def get_category_tree(self) -> dict[str, Any]:
        """The section hierarchy, as nested names.

        ``{"Light Micrscopy": {"Widefield Microscopy": {}, ...}, ...}`` — the
        only place the nesting is published. A guide's own payload names its
        section as a bare string with nothing above it, so an import that reads
        only guides produces a flat list of sections and loses which sits under
        which.
        """
        payload = self.get_json("/api/2.0/categories")
        if not isinstance(payload, dict):
            raise MigrationError("The category listing was not an object.")
        return payload

    def get_guide_tags(self, guide_id: str | int) -> list[str]:
        """The groups a guide belongs to, which its payload does not carry.

        ``/guides/56/tags`` answers ``["Balgrist Campus", "Confocal",
        "Laserscanning"]``. There is no ``tags`` key on the guide itself, so
        this is the only source — and an import that never called it recorded
        "0 tags" against a corpus that has eighty-nine of them driving thirteen
        section front pages.
        """
        payload = self.get_json(f"/api/2.0/guides/{guide_id}/tags")
        if not isinstance(payload, list):
            raise MigrationError(f"Tags for guide {guide_id} were not a list.")
        return [item for item in payload if isinstance(item, str)]

    def get_image(self, image_id: str | int) -> dict[str, Any]:
        """One image's own record, which is the only place its shapes exist.

        A guide payload lists an image's transcode URLs and nothing else: no
        ``markup`` key appears on it at any point, so the annotations drawn over
        a step image can only be had one request at a time from here.
        """
        payload = self.get_json(f"/api/2.0/media/images/{image_id}")
        if not isinstance(payload, dict):
            raise MigrationError(f"Image {image_id} was not an object.")
        return payload

    def iter_wikis(self, namespace: str = "CATEGORY") -> Iterator[dict[str, Any]]:
        yield from self._iter_listing(f"/api/2.0/wikis/{namespace}")

    def get_wiki(self, namespace: str, title: str) -> dict[str, Any]:
        quoted = urllib.parse.quote(title, safe="")
        payload = self.get_json(f"/api/2.0/wikis/{namespace}/{quoted}")
        if not isinstance(payload, dict):
            raise MigrationError(f"Wiki {namespace}/{title} was not an object.")
        return payload

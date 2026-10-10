"""The on-disk export: where each raw response and each media file lives.

The archive is the durable half of the import. It holds the vendor API's
responses byte for byte, so that a mapping mistake found months later can be
corrected by loading again, long after the API itself has gone. Layout::

    manifest.json                       what was fetched, when, with what result
    api/guides/index.json               every guide's list entry, de-duplicated
    api/guides/<id>/guide.json          GET /guides/<id>
    api/guides/<id>/tags.json           GET /guides/<id>/tags
    api/categories/tree.json            GET /categories
    api/categories/hierarchy.json       GET /wikis/CATEGORY?display=hierarchy
    api/categories/all.json             GET /categories/all, all pages
    api/categories/detail/<title>.json  GET /categories/<title>
    api/wikis/<NS>/index.json           GET /wikis/<NS>, all pages
    api/wikis/<NS>/<wikiid>.json        GET /wikis/<NS>/<title>
    api/wikis/<NS>/<wikiid>.tags.json   GET /wikis/<NS>/<title>/tags
    api/media/images/<id>.json          GET /media/images/<id>
    api/media/videos/<id>.json          GET /media/videos/<id>
    api/users/<id>.json                 GET /users/<id>
    files/images/<id>.<ext>             the original upload
    files/videos/<id>.<ext>             the best encoding the API offers

Every write is to a temporary file that is then renamed, so a file that exists
is a file that is complete — which is what lets an interrupted export resume by
skipping whatever is already there.

Credentials are never written here. User profiles are: they contain names and
e-mail addresses, so the archive is personal data and should be kept like it.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

MANIFEST = "manifest.json"
HASH_CHUNK_BYTES = 1024 * 1024


class ArchiveError(Exception):
    """The directory is not a usable export."""


def write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def write_json_atomic(path: Path, document: Any) -> None:
    write_bytes_atomic(path, json.dumps(document, ensure_ascii=False, indent=1).encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def title_filename(title: str) -> str:
    """A wiki title as a file name that can be turned back into the title."""
    return quote(title, safe="").replace(".", "%2E") or "%00"


def filename_title(name: str) -> str:
    return unquote(name).replace("\x00", "")


class Archive:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ paths

    def path(self, relative: str) -> Path:
        return self.root / relative

    @staticmethod
    def guide_index() -> str:
        return "api/guides/index.json"

    @staticmethod
    def guide(guide_id: int | str) -> str:
        return f"api/guides/{guide_id}/guide.json"

    @staticmethod
    def guide_tags(guide_id: int | str) -> str:
        return f"api/guides/{guide_id}/tags.json"

    @staticmethod
    def category_detail(title: str) -> str:
        return f"api/categories/detail/{title_filename(title)}.json"

    @staticmethod
    def wiki_index(namespace: str) -> str:
        return f"api/wikis/{namespace}/index.json"

    @staticmethod
    def wiki(namespace: str, wiki_id: int | str) -> str:
        return f"api/wikis/{namespace}/{wiki_id}.json"

    @staticmethod
    def wiki_tags(namespace: str, wiki_id: int | str) -> str:
        return f"api/wikis/{namespace}/{wiki_id}.tags.json"

    @staticmethod
    def image_meta(image_id: int | str) -> str:
        return f"api/media/images/{image_id}.json"

    @staticmethod
    def video_meta(video_id: int | str) -> str:
        return f"api/media/videos/{video_id}.json"

    @staticmethod
    def user(user_id: int | str) -> str:
        return f"api/users/{user_id}.json"

    # ------------------------------------------------------------ reading and writing

    def exists(self, relative: str) -> bool:
        return self.path(relative).is_file()

    def read_json(self, relative: str, default: Any = None) -> Any:
        """A stored response, or ``default`` when it is absent or unreadable."""
        try:
            with self.path(relative).open("rb") as stream:
                return json.load(stream)
        except (OSError, ValueError):
            return default

    def write_raw(self, relative: str, payload: bytes) -> None:
        write_bytes_atomic(self.path(relative), payload)

    def write_json(self, relative: str, document: Any) -> None:
        write_json_atomic(self.path(relative), document)

    def manifest(self) -> dict[str, Any]:
        document = self.read_json(MANIFEST)
        if not isinstance(document, dict) or not isinstance(document.get("items"), dict):
            raise ArchiveError(
                f"{self.root} has no readable {MANIFEST}; it is not an export made by `python -m app.importer export`."
            )
        return document

    def media_file(self, kind: str, vendor_id: int | str) -> Path | None:
        """The downloaded file for an image or a video, if the manifest has one."""
        entry = self.manifest_items().get(f"{kind}-file:{vendor_id}")
        if not entry or entry.get("status") != "ok" or not entry.get("path"):
            return None
        path = self.path(entry["path"])
        return path if path.is_file() else None

    def manifest_items(self) -> dict[str, Any]:
        if not hasattr(self, "_items"):
            self._items = self.manifest()["items"]
        return self._items

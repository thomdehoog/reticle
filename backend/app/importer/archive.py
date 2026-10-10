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

Nothing the vendor sends is trusted to name a file. Ids must be whole numbers,
namespaces plain upper-case words, and titles are percent-encoded; and every
read and write, whoever asks, goes through :meth:`Archive.path`, which refuses
an absolute path, a ``..``, and anything reached through a symbolic link. So an
id of ``../../x`` in an API response cannot write outside the archive, and a
doctored ``manifest.json`` cannot make ``load`` read a file from elsewhere.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

MANIFEST = "manifest.json"
HASH_CHUNK_BYTES = 1024 * 1024
MAX_ID_DIGITS = 18
NAMESPACE = re.compile(r"[A-Z][A-Z0-9_]{0,31}")
MAX_TITLE_FILENAME = 180
"""Longest file name a title may become; most file systems stop at 255 bytes."""


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


def safe_id(value: Any) -> int:
    """A vendor id as the whole number it has to be, or :class:`ArchiveError`.

    Ids become file names and URL path segments. The API sends them as JSON
    numbers; a string of digits is accepted because some list endpoints quote
    them. Anything else — ``"../../x"``, ``"7/tags"``, ``True``, ``-1``, ``1.5`` —
    is refused here, before it is near a path.
    """
    if isinstance(value, bool):
        raise ArchiveError(f"{value!r} is not a usable id")
    if isinstance(value, int) and 0 < value < 10**MAX_ID_DIGITS:
        return value
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= MAX_ID_DIGITS and int(value) > 0:
        return int(value)
    raise ArchiveError(f"{str(value)[:80]!r} is not a usable id")


def is_safe_id(value: Any) -> bool:
    try:
        safe_id(value)
    except ArchiveError:
        return False
    return True


def safe_namespace(value: Any) -> str:
    """A wiki namespace as the plain upper-case word it has to be."""
    if isinstance(value, str) and NAMESPACE.fullmatch(value):
        return value
    raise ArchiveError(f"{str(value)[:80]!r} is not a usable wiki namespace")


def title_filename(title: str) -> str:
    """A wiki title as a file name that can be turned back into the title.

    Every character but ASCII letters, digits, ``_``, ``-`` and ``~`` is
    percent-encoded, the full stop included, so the name holds no separator and
    can never be ``.`` or ``..``. A title too long for a file name is cut and
    given a digest of the whole of it; that one cannot be decoded again, which
    is why the loader takes the title from inside the file when it is there.
    """
    name = quote(title, safe="").replace(".", "%2E") or "%00"
    if len(name) > MAX_TITLE_FILENAME:
        digest = hashlib.sha256(title.encode("utf-8", "surrogatepass")).hexdigest()[:24]
        name = f"{name[:MAX_TITLE_FILENAME - 30].rstrip('%')}%00%00{digest}"
    return name


def filename_title(name: str) -> str:
    return unquote(name).replace("\x00", "")


class Archive:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ paths

    def path(self, relative: str) -> Path:
        """Where a relative archive path is on disk — the one gate for every read and write.

        The path has to stay inside the archive: it may not be absolute, may not
        step upwards, and may not pass through a symbolic link, at any level.
        The archive directory itself may be a link; what is refused is a link
        *inside* it, which is how a copied or doctored archive would point a
        read at some other file on the machine.
        """
        parts = relative.split("/") if isinstance(relative, str) else [""]
        if any(part in {"", ".", ".."} for part in parts) or "\\" in relative or "\x00" in relative or ":" in parts[0]:
            raise ArchiveError(f"{str(relative)[:120]!r} is not a path inside the archive")
        current = self.root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise ArchiveError(f"{relative!r} passes through a symbolic link; refusing to follow it out of the archive")
        return current

    def files(self, folder: str, pattern: str) -> list[str]:
        """The archive paths of the files under a folder that match a pattern, in order.

        Symbolic links are left out, and a folder that is itself reached through
        one holds nothing as far as the importer is concerned.
        """
        try:
            base = self.path(folder)
        except ArchiveError:
            return []
        return sorted(path.relative_to(self.root).as_posix() for path in base.glob(pattern) if path.is_file() and not path.is_symlink())

    @staticmethod
    def guide_index() -> str:
        return "api/guides/index.json"

    @staticmethod
    def guide(guide_id: Any) -> str:
        return f"api/guides/{safe_id(guide_id)}/guide.json"

    @staticmethod
    def guide_tags(guide_id: Any) -> str:
        return f"api/guides/{safe_id(guide_id)}/tags.json"

    @staticmethod
    def category_detail(title: str) -> str:
        return f"api/categories/detail/{title_filename(title)}.json"

    @staticmethod
    def wiki_index(namespace: str) -> str:
        return f"api/wikis/{safe_namespace(namespace)}/index.json"

    @staticmethod
    def wiki(namespace: str, wiki_id: Any) -> str:
        return f"api/wikis/{safe_namespace(namespace)}/{safe_id(wiki_id)}.json"

    @staticmethod
    def wiki_tags(namespace: str, wiki_id: Any) -> str:
        return f"api/wikis/{safe_namespace(namespace)}/{safe_id(wiki_id)}.tags.json"

    @staticmethod
    def image_meta(image_id: Any) -> str:
        return f"api/media/images/{safe_id(image_id)}.json"

    @staticmethod
    def video_meta(video_id: Any) -> str:
        return f"api/media/videos/{safe_id(video_id)}.json"

    @staticmethod
    def user(user_id: Any) -> str:
        return f"api/users/{safe_id(user_id)}.json"

    # ------------------------------------------------------------ reading and writing

    def exists(self, relative: str) -> bool:
        try:
            return self.path(relative).is_file()
        except ArchiveError:
            return False

    def read_json(self, relative: str, default: Any = None) -> Any:
        """A stored response, or ``default`` when it is absent, unreadable or not safely inside the archive."""
        try:
            with self.path(relative).open("rb") as stream:
                return json.load(stream)
        except (OSError, ValueError, ArchiveError):
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
        if not isinstance(entry, dict) or entry.get("status") != "ok" or not entry.get("path"):
            return None
        try:
            path = self.path(entry["path"])
        except ArchiveError:
            return None
        return path if path.is_file() else None

    def manifest_items(self) -> dict[str, Any]:
        if not hasattr(self, "_items"):
            self._items = self.manifest()["items"]
        return self._items

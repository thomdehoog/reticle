"""Phase one: copy a site's content out through the vendor API, onto disk.

The export is the part with a deadline. The API answers only while the
subscription runs, so everything it will give is taken now and kept raw: the
exact JSON of each response and the original media files. Deciding what any of
it means is left to ``load``, which can be re-run for as long as the archive
exists.

It is built to be interrupted. Each item is fetched, written to a temporary
file, renamed into place and recorded in the manifest; a second run skips what
is already there, so a dropped connection or an expired token costs the time
since the last item and nothing more. One item that cannot be fetched is
recorded and the run carries on — the summary lists every one, and the exit
status is non-zero if there were any.

Two things are remembered from one run to the next, in the manifest. An item
the site said it does not have is marked ``absent`` with the time it was asked
for, and is not asked for again unless ``--refresh`` is given or the run has
credentials the earlier one lacked. And the images used by a guide or page that
was fetched again because it changed are queued for a second look, because an
image's markers can be edited without its id changing: their metadata is
fetched again, and the picture is downloaded again if the two differ.

The export also records what the site shows to a visitor who is not signed in:
one extra listing pass without credentials per listing, no request per item.
``load`` uses that to decide which pages may be published.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ARCHIVE_FORMAT, TOOL_NAME, TOOL_VERSION
from .archive import MANIFEST, Archive, ArchiveError, is_safe_id, safe_id, safe_namespace, sha256_file
from .client import MAX_IMAGE_BYTES, MAX_VIDEO_BYTES, AuthenticationError, ClientError, DozukiClient, NotFound, path_segment
from .wikitext import referenced_image_ids

PAGE_SIZE = 200
SMALLER_PAGE_SIZES = (100, 20)
"""Tried in turn if the site refuses the first page at ``PAGE_SIZE``.

200 is the documented maximum for guides; for the wiki and category listings the
limit is not documented, and 20 is the documented default everywhere.
"""
MAX_PAGES = 500
DEFAULT_NAMESPACES = ("CATEGORY", "WIKI", "INFO", "ITEM")
"""Wiki namespaces fetched by default.

``USER`` and ``TEAM`` pages are personal profile pages rather than facility
documentation and are left out unless asked for.
"""

MANIFEST_EVERY = 25
GUIDE_PROGRESS_EVERY = 25
IMAGE_PROGRESS_EVERY = 100

IMAGE_RENDITIONS = ("original", "huge", "large", "medium", "standard")
"""Preference order for the file to keep; ``original`` is the full-size upload."""

CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tif",
    "image/svg+xml": "svg",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/ogg": "ogv",
    "video/quicktime": "mov",
}
ENCODING_EXTENSIONS = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}
PLAYABLE_VIDEO = frozenset({"mp4", "webm"})
SAFE_EXTENSION = re.compile(r"[a-z0-9]{1,8}")
TEMPORARY_SUFFIXES = frozenset({".part", ".download", ".tmp"})
CONTENT_KINDS = frozenset({"guide", "wiki", "category"})
"""Responses that name the media they use."""
ANONYMOUS_VISIBLE = "anonymousVisible"
"""Added to every guide and wiki index entry: ``true`` if the site listed the
item to a request without credentials, ``false`` if it did not, ``null`` if that
could not be found out. It is the importer's own field, not the vendor's."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def is_image_object(value: Any) -> bool:
    """Whether a JSON object is one of the vendor's image records.

    Placeholders must not count: a wiki without a picture carries an object of
    default-artwork URLs with no ``id``, and a user without an avatar carries a
    negative one.
    """
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), int)
        and not isinstance(value.get("id"), bool)
        and value["id"] > 0
        and isinstance(value.get("guid"), str)
    )


def is_video_object(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("videoid"), int)
        and not isinstance(value.get("videoid"), bool)
        and value["videoid"] > 0
        and isinstance(value.get("encodings"), list)
    )


def picture_identity(meta: dict[str, Any]) -> str:
    """Everything in an image's metadata that changes when the picture or its markers do."""
    record = meta.get("image") if isinstance(meta.get("image"), dict) else {}
    facts = [record.get("guid"), meta.get("srcid"), meta.get("width"), meta.get("height"), meta.get("markup"), meta.get("markupState")]
    return json.dumps(facts, sort_keys=True, default=str)


def walk(value: Any, skip: frozenset[str] = frozenset({"author"})) -> Iterator[Any]:
    """Every object and string in a response, except under keys that are not content."""
    yield value
    if isinstance(value, dict):
        for key, child in value.items():
            if key not in skip:
                yield from walk(child, skip)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, skip)


def referenced_media(document: Any) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    """The images and videos a response uses: ``{id: embedded object}`` for each.

    Images are found two ways — as embedded image records, and as
    ``[image|<id>]`` tags inside any ``*_raw`` wiki text, which carry an id and
    nothing else.
    """
    images: dict[int, dict[str, Any]] = {}
    videos: dict[int, dict[str, Any]] = {}
    for node in walk(document):
        if is_video_object(node):
            videos.setdefault(node["videoid"], node)
        elif is_image_object(node):
            images.setdefault(node["id"], node)
        elif isinstance(node, dict):
            for key, text in node.items():
                if key.endswith("_raw") and isinstance(text, str):
                    for image_id in referenced_image_ids(text):
                        images.setdefault(image_id, {})
    return images, videos


def best_encoding(video: dict[str, Any]) -> dict[str, Any] | None:
    """The encoding to keep: one a browser can play if there is one, then the largest."""
    candidates = [entry for entry in video.get("encodings") or [] if isinstance(entry, dict) and entry.get("url")]
    if not candidates:
        return None

    def rank(entry: dict[str, Any]) -> tuple[int, int]:
        playable = encoding_extension(entry) in PLAYABLE_VIDEO
        area = int(entry.get("width") or 0) * int(entry.get("height") or 0)
        return (1 if playable else 0, area)

    return max(candidates, key=rank)


def encoding_extension(entry: dict[str, Any]) -> str:
    mime = str(entry.get("mime") or "").split(";")[0].strip().lower()
    if mime in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[mime]
    declared = str(entry.get("format") or "").strip().lower()
    if declared.isalnum() and declared:
        return declared
    suffix = Path(str(entry.get("url") or "").split("?")[0]).suffix.lstrip(".").lower()
    return suffix if suffix.isalnum() and suffix else "bin"


def category_titles(tree: Any) -> list[tuple[str, str | None]]:
    """``(title, parent title)`` for every node of a nested category object.

    Leaves arrive as ``{}``, ``[]`` or ``null`` depending on the endpoint.
    """
    found: list[tuple[str, str | None]] = []

    def visit(node: Any, parent: str | None) -> None:
        if isinstance(node, dict):
            for title, children in node.items():
                found.append((str(title), parent))
                visit(children, str(title))

    visit(tree, None)
    return found


class Exporter:
    def __init__(
        self,
        client: DozukiClient,
        archive: Archive,
        *,
        namespaces: tuple[str, ...] = DEFAULT_NAMESPACES,
        refresh: bool = False,
        log: Callable[[str], None] = print,
        max_image_bytes: int = MAX_IMAGE_BYTES,
        max_video_bytes: int = MAX_VIDEO_BYTES,
    ) -> None:
        self.client = client
        self.archive = archive
        self.namespaces = tuple(safe_namespace(namespace.upper()) for namespace in namespaces)
        self.refresh = refresh
        self.log = log
        self.max_image_bytes = max_image_bytes
        self.max_video_bytes = max_video_bytes
        self.recheck_images: set[int] = set()
        self._images_exported_before = False
        self.items: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.started_at = utc_now()
        self.include_private = client.authenticated
        self._since_save = 0
        previous = archive.read_json(MANIFEST)
        if isinstance(previous, dict) and isinstance(previous.get("items"), dict):
            self.items = {
                key: entry for key, entry in previous["items"].items() if isinstance(entry, dict) and entry.get("kind") and entry.get("status")
            }
            self.started_at = previous.get("started_at") or self.started_at
            pending = previous.get("recheck_images")
            self.recheck_images = {image_id for image_id in pending if is_safe_id(image_id)} if isinstance(pending, list) else set()
            self._images_exported_before = any(entry["kind"] == "image-meta" for entry in self.items.values())

    # ------------------------------------------------------------ bookkeeping

    def record(self, key: str, kind: str, status: str, **fields: Any) -> None:
        entry = {"kind": kind, "status": status, **{name: value for name, value in fields.items() if value is not None}}
        self.items[key] = entry
        if status == "failed":
            self.log(f"  FAILED {key}: {fields.get('error')}")
        self._since_save += 1
        if self._since_save >= MANIFEST_EVERY:
            self.save_manifest()

    def counts(self) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {}
        for entry in self.items.values():
            bucket = counts.setdefault(entry["kind"], {})
            bucket[entry["status"]] = bucket.get(entry["status"], 0) + 1
        return dict(sorted(counts.items()))

    def failures(self) -> dict[str, str]:
        return {key: entry.get("error", "") for key, entry in self.items.items() if entry["status"] == "failed"}

    def save_manifest(self, finished: bool = False) -> None:
        self._since_save = 0
        self.archive.write_json(
            MANIFEST,
            {
                "tool": TOOL_NAME,
                "tool_version": TOOL_VERSION,
                "format": ARCHIVE_FORMAT,
                "site": self.client.host,
                "api_base": self.client.base,
                "started_at": self.started_at,
                "updated_at": utc_now(),
                "finished_at": utc_now() if finished else None,
                "authenticated": self.client.authenticated,
                "include_private": self.include_private,
                "namespaces": list(self.namespaces),
                "counts": self.counts(),
                "warnings": self.warnings,
                "recheck_images": sorted(self.recheck_images),
                "items": self.items,
            },
        )

    def warn(self, message: str) -> None:
        self.warnings.append(message)
        self.log(f"WARNING: {message}")

    # ------------------------------------------------------------ fetching

    def fetch(
        self,
        key: str,
        kind: str,
        path: str,
        relative: str,
        *,
        params: dict[str, Any] | None = None,
        optional: bool = False,
        reuse: bool = True,
        confirmed: bool = False,
    ) -> Any:
        """Fetch one response and store it raw, or take it from disk if it is there.

        ``optional`` marks something that may legitimately not exist (a category
        with no page, a namespace the site does not use): its absence is noted
        with the time, is not a failure, and is not asked about again on a later
        run — unless that run has ``--refresh``, or is signed in where the run
        that recorded the absence was not, since what an anonymous visitor may
        not see can exist all the same.

        ``confirmed`` says the caller has just compared the copy on disk with
        the site's listing and found it current; the manifest then records when.
        """
        previous = self.items.get(key, {})
        if reuse and not self.refresh and self.archive.exists(relative):
            stored = self.archive.read_json(relative)
            if stored is not None:
                self.record(
                    key, kind, "ok", path=relative, fetched_at=previous.get("fetched_at"), bytes=previous.get("bytes"),
                    confirmed_at=utc_now() if confirmed else previous.get("confirmed_at"),
                )
                return stored
        if (
            optional
            and not self.refresh
            and previous.get("status") == "absent"
            and (previous.get("authenticated") or not self.client.authenticated)
        ):
            self.record(key, kind, "absent", checked_at=previous.get("checked_at"), authenticated=bool(previous.get("authenticated")))
            return None
        try:
            document, body = self.client.get(path, params)
        except AuthenticationError:
            raise
        except NotFound as error:
            if optional:
                self.record(key, kind, "absent", checked_at=utc_now(), authenticated=self.client.authenticated)
            else:
                self.record(key, kind, "failed", error=str(error))
            return None
        except ClientError as error:
            self.record(key, kind, "failed", error=str(error))
            return None
        try:
            self.archive.write_raw(relative, body)
        except ArchiveError as error:
            self.record(key, kind, "failed", error=str(error))
            return None
        self.record(key, kind, "ok", path=relative, fetched_at=utc_now(), bytes=len(body))
        if kind in CONTENT_KINDS and self._images_exported_before:
            # The item is new or has changed, and images were exported before:
            # any of them may have been re-marked since. See export_media.
            self.recheck_images.update(referenced_media(document)[0])
        return document

    def pages(self, path: str, params: dict[str, Any], identity: Callable[[Any], Any], anonymous: bool = False) -> list[Any]:
        """Page through a list until an empty page.

        A short page is not the last page: the vendor applies the limit before
        it removes rows the caller may not see. The loop also stops if a page
        brings nothing new, so a server that ignores ``offset`` cannot spin it.
        """
        collected: list[Any] = []
        seen: set[Any] = set()
        sizes = [PAGE_SIZE, *(size for size in SMALLER_PAGE_SIZES if size < PAGE_SIZE)]
        size = sizes.pop(0)
        for page in range(MAX_PAGES):
            while True:
                try:
                    batch, _ = self.client.get(path, {**params, "limit": size, "offset": page * size}, anonymous=anonymous)
                    break
                except (AuthenticationError, NotFound):
                    raise
                except ClientError as refusal:
                    if page or not sizes or refusal.status is None or not 400 <= refusal.status < 500:
                        raise
                    self.log(f"  {path}: a page of {size} was refused ({refusal}); trying {sizes[0]}")
                    size = sizes.pop(0)
            if not isinstance(batch, list) or not batch:
                break
            fresh = 0
            for entry in batch:
                marker = identity(entry)
                if not isinstance(marker, (int, str, type(None))):
                    marker = repr(marker)  # an id of some other JSON type: unusable later, but must not break the paging
                if marker in seen:
                    continue
                seen.add(marker)
                collected.append(entry)
                fresh += 1
            if fresh == 0:
                break
        return collected

    def mark_visibility(self, entries: list[dict[str, Any]], path: str, field: str) -> None:
        """Record on each listing entry whether the site shows it to an anonymous visitor.

        An export without credentials has its answer already: everything it was
        given, it was given anonymously. A signed-in export pages through the
        same listing once more with no credentials and compares. If that pass
        fails — a site that shows nothing without a login answers 401 — the
        answer is recorded as unknown, and ``load`` treats unknown as "not
        shown to be public".
        """
        visible: set[Any] | None = None
        if self.client.authenticated:
            try:
                listed = self.pages(path, {}, lambda entry: entry.get(field) if isinstance(entry, dict) else None, anonymous=True)
            except ClientError as error:
                self.warn(
                    f"The anonymous listing of {path} could not be fetched ({error}), so the export cannot tell which of "
                    "its items were publicly visible; `load` will import those pages as drafts."
                )
                for entry in entries:
                    entry[ANONYMOUS_VISIBLE] = None
                return
            visible = {safe_id(entry[field]) for entry in listed if isinstance(entry, dict) and is_safe_id(entry.get(field))}
        for entry in entries:
            entry[ANONYMOUS_VISIBLE] = True if visible is None else entry[field] in visible

    def usable_entries(self, listing: list[Any], field: str, what: str, also: Callable[[dict[str, Any]], bool] = lambda entry: True) -> list[dict[str, Any]]:
        """The entries of a listing whose id is a whole number, with that id as an ``int``.

        Ids go into request paths and file names. An entry whose id is anything
        else is left out and counted in a warning, never passed on.
        """
        usable: list[dict[str, Any]] = []
        refused = 0
        for entry in listing:
            if not isinstance(entry, dict) or entry.get(field) is None:
                continue
            if not is_safe_id(entry[field]):
                refused += 1
            elif also(entry):
                usable.append({**entry, field: safe_id(entry[field])})
        if refused:
            self.warn(f"{refused} {what} with an id that is not a whole number were ignored.")
        return usable

    # ------------------------------------------------------------ the run

    def run(self) -> dict[str, Any]:
        self.archive.root.mkdir(parents=True, exist_ok=True)
        try:
            guides = self.export_guides()
            self.export_categories(guides)
            for namespace in self.namespaces:
                self.export_wikis(namespace)
            self.export_media()
            self.export_users()
            self.save_manifest(finished=True)
        except BaseException:
            self.save_manifest()
            raise
        return self.archive.manifest()

    def export_guides(self) -> list[dict[str, Any]]:
        self.log("Listing guides…")
        guides: list[dict[str, Any]] | None = None
        params: dict[str, Any] = {"includePrivate": "true"} if self.include_private else {}
        try:
            guides = self.pages("/guides", params, lambda entry: entry.get("guideid") if isinstance(entry, dict) else None)
        except AuthenticationError:
            raise
        except ClientError as error:
            if self.include_private and error.status is not None and 400 <= error.status < 500:
                self.include_private = False
                self.warn(
                    f"The site refused includePrivate ({error}). Listing public guides only: private and "
                    "unpublished guides will be MISSING. The account probably lacks administrator rights."
                )
                try:
                    guides = self.pages("/guides", {}, lambda entry: entry.get("guideid") if isinstance(entry, dict) else None)
                except AuthenticationError:
                    raise
                except ClientError as second:
                    self.record("guide-index", "guide-index", "failed", error=str(second))
            else:
                self.record("guide-index", "guide-index", "failed", error=str(error))

        if guides is None:
            stored = self.archive.read_json(Archive.guide_index())
            guides = [entry for entry in stored if isinstance(entry, dict) and is_safe_id(entry.get("guideid"))] if isinstance(stored, list) else []
            if guides:
                self.warn("The guide list could not be fetched; continuing with the list from the previous run.")
        else:
            guides = self.usable_entries(guides, "guideid", "guide listing entries")
            self.mark_visibility(guides, "/guides", "guideid")
            previous = self.archive.read_json(Archive.guide_index())
            known = {entry.get("guideid") for entry in guides}
            if isinstance(previous, list):
                kept = [entry for entry in previous if isinstance(entry, dict) and is_safe_id(entry.get("guideid")) and entry["guideid"] not in known]
                if kept:
                    self.warn(
                        f"{len(kept)} guide(s) from an earlier run are no longer listed by the site; "
                        "their exported copies are kept."
                    )
                    guides.extend(kept)
            guides.sort(key=lambda entry: entry["guideid"])
            self.archive.write_json(Archive.guide_index(), guides)
            self.record("guide-index", "guide-index", "ok", path=Archive.guide_index(), fetched_at=utc_now(), count=len(guides))

        self.log(f"{len(guides)} guides to export.")
        for number, entry in enumerate(guides, start=1):
            guide_id = entry["guideid"]
            stored = self.archive.read_json(Archive.guide(guide_id))
            current = isinstance(stored, dict) and all(
                stored.get(field) == entry.get(field) for field in ("guide_revisionid", "modified_date") if field in entry
            )
            if number % GUIDE_PROGRESS_EVERY == 0:
                self.log(f"  guide {number} of {len(guides)}")
            self.fetch(
                f"guide:{guide_id}",
                "guide",
                f"/guides/{guide_id}",
                Archive.guide(guide_id),
                params={"excludePrerequisiteSteps": "true"},
                reuse=current,
                confirmed=True,
            )
            self.fetch(
                f"guide-tags:{guide_id}", "guide-tags", f"/guides/{guide_id}/tags", Archive.guide_tags(guide_id), reuse=current, confirmed=True
            )
        return guides

    def export_categories(self, guides: list[dict[str, Any]]) -> None:
        self.log("Exporting categories…")
        titles: dict[str, None] = {}
        tree = self.fetch("category-tree", "category-tree", "/categories", "api/categories/tree.json", params={"includeStubs": "true"})
        hierarchy = self.fetch(
            "category-hierarchy", "category-tree", "/wikis/CATEGORY", "api/categories/hierarchy.json",
            params={"display": "hierarchy", "includeStubs": "true"}, optional=True,
        )
        for title, _ in category_titles(tree):
            titles.setdefault(title)
        if isinstance(hierarchy, dict):
            for title, _ in category_titles(hierarchy.get("hierarchy")):
                titles.setdefault(title)
            for title in hierarchy.get("display_titles") or {}:
                titles.setdefault(str(title))

        try:
            flat = self.pages("/categories/all", {}, lambda entry: entry)
            self.archive.write_json("api/categories/all.json", flat)
            self.record("category-all", "category-tree", "ok", path="api/categories/all.json", fetched_at=utc_now(), count=len(flat))
            for title in flat:
                if isinstance(title, str):
                    titles.setdefault(title)
        except AuthenticationError:
            raise
        except ClientError as error:
            self.record("category-all", "category-tree", "absent" if isinstance(error, NotFound) else "failed", error=str(error))

        for entry in guides:
            if entry.get("category"):
                titles.setdefault(str(entry["category"]))
            stored = self.archive.read_json(Archive.guide(entry["guideid"]))
            if isinstance(stored, dict) and stored.get("category"):
                titles.setdefault(str(stored["category"]))

        queue = list(titles)
        while queue:
            title = queue.pop(0)
            detail = self.fetch(
                f"category:{title}", "category", f"/categories/{path_segment(title)}", Archive.category_detail(title), optional=True
            )
            if isinstance(detail, dict):
                for child in detail.get("children") or []:
                    if isinstance(child, str) and child not in titles:
                        titles[child] = None
                        queue.append(child)

    def export_wikis(self, namespace: str) -> None:
        self.log(f"Exporting {namespace} pages…")
        key = f"wiki-index:{namespace}"
        try:
            listing = self.pages(f"/wikis/{namespace}", {}, lambda entry: entry.get("wikiid") if isinstance(entry, dict) else None)
        except AuthenticationError:
            raise
        except ClientError as error:
            core = namespace in {"CATEGORY", "WIKI"}
            self.record(key, "wiki-index", "failed" if core and not isinstance(error, NotFound) else "absent", error=str(error))
            stored = self.archive.read_json(Archive.wiki_index(namespace))
            listing = (
                [entry for entry in stored if isinstance(entry, dict) and is_safe_id(entry.get("wikiid")) and entry.get("title")]
                if isinstance(stored, list)
                else []
            )
        else:
            listing = self.usable_entries(listing, "wikiid", f"{namespace} page listing entries", lambda entry: bool(entry.get("title")))
            self.mark_visibility(listing, f"/wikis/{namespace}", "wikiid")
            if namespace == "CATEGORY":
                listing.extend(self._unlisted_category_pages({entry["wikiid"] for entry in listing}))
            self.archive.write_json(Archive.wiki_index(namespace), listing)
            self.record(key, "wiki-index", "ok", path=Archive.wiki_index(namespace), fetched_at=utc_now(), count=len(listing))

        for entry in listing:
            wiki_id, title = entry["wikiid"], str(entry["title"])
            stored = self.archive.read_json(Archive.wiki(namespace, wiki_id))
            current = isinstance(stored, dict) and stored.get("revisionid") == entry.get("revisionid")
            segment = path_segment(title)
            self.fetch(
                f"wiki:{namespace}:{wiki_id}", "wiki", f"/wikis/{namespace}/{segment}", Archive.wiki(namespace, wiki_id), reuse=current, confirmed=True
            )
            self.fetch(
                f"wiki-tags:{namespace}:{wiki_id}", "wiki-tags", f"/wikis/{namespace}/{segment}/tags",
                Archive.wiki_tags(namespace, wiki_id), optional=True, reuse=current, confirmed=True,
            )

    def _unlisted_category_pages(self, listed: set[Any]) -> list[dict[str, Any]]:
        """Index entries for category pages the wiki listing leaves out.

        Every category is a wiki page, but the listing was seen to return fewer
        titles than there are categories — the holding categories among them.
        Their pages are asked for by title, and those that exist join the index.
        """
        extra: list[dict[str, Any]] = []
        for relative in self.archive.files("api/categories/detail", "*.json"):
            detail = self.archive.read_json(relative)
            if not isinstance(detail, dict):
                continue
            wiki_id, title = detail.get("wikiid"), detail.get("wiki_title")
            if not isinstance(wiki_id, int) or not is_safe_id(wiki_id) or not isinstance(title, str) or not title or wiki_id in listed:
                continue
            listed.add(wiki_id)
            page = self.fetch(
                f"wiki:CATEGORY:{wiki_id}", "wiki", f"/wikis/CATEGORY/{path_segment(title)}", Archive.wiki("CATEGORY", wiki_id), optional=True
            )
            if isinstance(page, dict):
                extra.append(
                    {
                        "dataType": "wiki", "wikiid": wiki_id, "revisionid": page.get("revisionid"), "title": title,
                        "display_title": page.get("display_title") or detail.get("display_title") or title,
                        "namespace": "CATEGORY", "summary": page.get("description") or "", "image": page.get("image"),
                        "modified_date": None, "listed": False,
                        # Asked for by title, so only an anonymous export knows that a visitor could read it.
                        ANONYMOUS_VISIBLE: None if self.client.authenticated else True,
                    }
                )
        return extra

    # ------------------------------------------------------------ media

    def stored_documents(self) -> Iterator[Any]:
        """Every content response on disk whose media the export must hold."""
        for relative in self.archive.files("api", "guides/*/guide.json"):
            yield self.archive.read_json(relative)
        for relative in self.archive.files("api", "wikis/*/*.json"):
            if not relative.endswith(("/index.json", ".tags.json")):
                yield self.archive.read_json(relative)
        for relative in self.archive.files("api", "wikis/*/index.json"):
            yield self.archive.read_json(relative)
        for relative in self.archive.files("api", "categories/detail/*.json"):
            document = self.archive.read_json(relative)
            if isinstance(document, dict):
                yield {key: value for key, value in document.items() if key != "guides"}

    def export_media(self) -> None:
        images: dict[int, dict[str, Any]] = {}
        videos: dict[int, dict[str, Any]] = {}
        for document in self.stored_documents():
            found_images, found_videos = referenced_media(document)
            for image_id, embedded in found_images.items():
                if not images.get(image_id):
                    images[image_id] = embedded
            for video_id, embedded in found_videos.items():
                videos.setdefault(video_id, embedded)

        self.log(f"Exporting {len(videos)} videos…")
        for video_id, embedded in sorted(videos.items()):
            meta = self.fetch(f"video-meta:{video_id}", "video-meta", f"/media/videos/{video_id}", Archive.video_meta(video_id))
            for image_id, poster in referenced_media(meta if isinstance(meta, dict) else embedded)[0].items():
                images.setdefault(image_id, poster)
            self.download_video(video_id, meta if is_video_object(meta) else embedded)

        self.log(f"Exporting {len(images)} images (plus the clean source of each marked-up one)…")
        queue = sorted(images)
        done = 0
        while queue:
            image_id = queue.pop(0)
            # An image's markers can be edited without its id changing, and its
            # metadata carries no modification date. So when the guide or page
            # that uses it was fetched again, the metadata is too, and if that
            # shows a different picture or different markers, so is the file.
            recheck = image_id in self.recheck_images
            before = self.archive.read_json(Archive.image_meta(image_id)) if recheck else None
            meta = self.fetch(f"image-meta:{image_id}", "image-meta", f"/media/images/{image_id}", Archive.image_meta(image_id), reuse=not recheck)
            changed = isinstance(before, dict) and isinstance(meta, dict) and picture_identity(before) != picture_identity(meta)
            if changed:
                self.log(f"  image {image_id} changed on the site (its picture or its markers); downloading it again")
            self.download_image(image_id, meta if isinstance(meta, dict) else {}, images.get(image_id) or {}, replace=changed)
            self.recheck_images.discard(image_id)
            source_id = meta.get("srcid") if isinstance(meta, dict) else None
            if isinstance(source_id, int) and source_id > 0 and source_id not in images:
                info = meta.get("srcImageInfo")
                images[source_id] = info.get("image") if isinstance(info, dict) and is_image_object(info.get("image")) else {}
                queue.append(source_id)
            done += 1
            if done % IMAGE_PROGRESS_EVERY == 0:
                self.log(f"  image {done} of {len(images)}")

    def _already_downloaded(self, key: str, kind: str, folder: str, vendor_id: int) -> bool:
        """Whether the file is on disk from an earlier run, adopting it if the manifest lost track."""
        entry = self.items.get(key)
        if entry and entry.get("status") == "ok" and entry.get("path") and self.archive.exists(entry["path"]):
            if self.archive.path(entry["path"]).stat().st_size == entry.get("bytes"):
                return True
        if self.refresh:
            return False
        for relative in self.archive.files(folder, f"{vendor_id}.*"):
            path = self.archive.path(relative)
            if path.suffix in TEMPORARY_SUFFIXES:
                continue
            self.record(key, kind, "ok", path=relative, sha256=sha256_file(path), bytes=path.stat().st_size, adopted=True)
            return True
        return False

    def _download(
        self, key: str, kind: str, folder: str, vendor_id: int, url: str, extension: Callable[[str], str], expect: str, max_bytes: int,
        **fields: Any,
    ) -> None:
        """Download one media file into the archive and describe it in the manifest.

        The URL came out of an API response, so the client treats it as an
        address somebody else chose (see :mod:`.client`). The manifest keeps the
        type the server declared, the type the file was taken to be, and the
        final address if the download was redirected.
        """
        try:
            temporary = self.archive.path(f"{folder}/{vendor_id}.download")
            result = self.client.download(url, temporary, expect=expect, max_bytes=max_bytes)
        except (ClientError, ArchiveError) as error:
            self.record(key, kind, "failed", error=str(error), url=url)
            return
        suffix = extension(result.content_type)
        relative = f"{folder}/{vendor_id}.{suffix if SAFE_EXTENSION.fullmatch(suffix) else 'bin'}"
        target = self.archive.path(relative)
        temporary.replace(target)
        for other in self.archive.files(folder, f"{vendor_id}.*"):
            if other != relative and Path(other).suffix not in TEMPORARY_SUFFIXES:
                self.archive.path(other).unlink()  # an earlier copy under another extension, now superseded
        self.record(
            key, kind, "ok", path=relative, sha256=result.sha256, bytes=result.size, url=url,
            content_type=result.content_type or None,
            declared_content_type=result.declared_type if result.declared_type != result.content_type else None,
            final_url=result.final_url if result.final_url != url else None,
            fetched_at=utc_now(), **fields,
        )

    def download_image(self, image_id: int, meta: dict[str, Any], embedded: dict[str, Any], replace: bool = False) -> None:
        key = f"image-file:{image_id}"
        if not replace and self._already_downloaded(key, "image-file", "files/images", image_id):
            return
        record = meta.get("image") if isinstance(meta.get("image"), dict) else {}
        url, rendition = None, None
        for source in (record, embedded):
            for name in IMAGE_RENDITIONS:
                if isinstance(source.get(name), str) and source[name]:
                    url, rendition = source[name], name
                    break
            if url:
                break
        if url is None:
            self.record(key, "image-file", "failed", error="no download URL in the image metadata")
            return
        if rendition != "original":
            self.warn(f"Image {image_id} has no original rendition; kept the “{rendition}” one.")

        def extension(content_type: str) -> str:
            if content_type in CONTENT_TYPE_EXTENSIONS:
                return CONTENT_TYPE_EXTENSIONS[content_type]
            return ENCODING_EXTENSIONS.get(str(meta.get("encoding") or "").lower(), "bin")

        self._download(key, "image-file", "files/images", image_id, url, extension, "image", self.max_image_bytes, rendition=rendition)

    def download_video(self, video_id: int, video: dict[str, Any]) -> None:
        key = f"video-file:{video_id}"
        if self._already_downloaded(key, "video-file", "files/videos", video_id):
            return
        encoding = best_encoding(video)
        if encoding is None:
            self.record(key, "video-file", "failed", error="the video offers no encoding to download")
            return
        self._download(
            key, "video-file", "files/videos", video_id, str(encoding["url"]), lambda _content_type: encoding_extension(encoding),
            "video", self.max_video_bytes,
            encoding=encoding.get("column") or encoding.get("label"), width=encoding.get("width"), height=encoding.get("height"),
        )

    def export_users(self) -> None:
        user_ids: set[int] = set()
        for document in [self.archive.read_json(Archive.guide_index())] + list(self.stored_documents()):
            for node in walk(document, skip=frozenset()):
                if isinstance(node, dict):
                    candidate = node.get("userid")
                    if isinstance(candidate, int) and not isinstance(candidate, bool) and candidate > 0:
                        user_ids.add(candidate)
        self.log(f"Exporting {len(user_ids)} author profiles…")
        for user_id in sorted(user_ids):
            self.fetch(f"user:{user_id}", "user", f"/users/{user_id}", Archive.user(user_id))


# ---------------------------------------------------------------- verification


def verify_archive(archive: Archive) -> tuple[list[str], dict[str, int]]:
    """Re-check an export without touching the network.

    Returns the problems found and a few counts. An archive passes when every
    listed guide and page is present and readable, every image and video they
    use is on disk, and every media file still has the checksum it was written
    with.
    """
    problems: list[str] = []
    stats = {"guides": 0, "pages": 0, "images": 0, "videos": 0, "files_checked": 0}
    try:
        manifest = archive.manifest()
    except ArchiveError as error:
        return [str(error)], stats
    items: dict[str, Any] = {key: entry for key, entry in manifest["items"].items() if isinstance(entry, dict)}
    if len(items) != len(manifest["items"]):
        problems.append(f"{len(manifest['items']) - len(items)} manifest entries are not readable entries; the files they stood for count as missing.")

    if not manifest.get("finished_at"):
        problems.append("The export did not run to completion (no finished_at in the manifest); run it again to resume.")
    for key, entry in sorted(items.items()):
        if entry.get("status") == "failed":
            problems.append(f"{key}: failed during export — {entry.get('error', 'no reason recorded')}")

    for key, entry in sorted(items.items()):
        if entry.get("status") != "ok" or not entry.get("path"):
            continue
        try:
            path = archive.path(entry["path"])
        except ArchiveError as error:
            problems.append(f"{key}: {error}")
            continue
        if not path.is_file():
            problems.append(f"{key}: file {entry['path']} is missing")
            continue
        if entry.get("sha256"):
            stats["files_checked"] += 1
            if sha256_file(path) != entry["sha256"]:
                problems.append(f"{key}: {entry['path']} does not match its recorded checksum")
        else:
            try:
                json.loads(path.read_bytes())
            except ValueError:
                problems.append(f"{key}: {entry['path']} is not readable JSON")

    def check_media(owner: str, document: Any) -> None:
        images, videos = referenced_media(document)
        for image_id in sorted(images):
            stats["images"] += 1
            if archive.media_file("image", image_id) is None:
                problems.append(f"{owner}: image {image_id} has no downloaded file")
            meta = archive.read_json(Archive.image_meta(image_id))
            if not isinstance(meta, dict):
                problems.append(f"{owner}: image {image_id} has no metadata (markers cannot be imported)")
            elif isinstance(meta.get("srcid"), int) and meta["srcid"] > 0 and archive.media_file("image", meta["srcid"]) is None:
                problems.append(f"{owner}: clean source {meta['srcid']} of marked-up image {image_id} has no downloaded file")
        for video_id in sorted(videos):
            stats["videos"] += 1
            if archive.media_file("video", video_id) is None:
                problems.append(f"{owner}: video {video_id} has no downloaded file")

    index = archive.read_json(Archive.guide_index())
    if not isinstance(index, list):
        problems.append("The guide index (api/guides/index.json) is missing or unreadable.")
        index = []
    for entry in index:
        guide_id = entry.get("guideid") if isinstance(entry, dict) else None
        stats["guides"] += 1
        if not is_safe_id(guide_id):
            problems.append(f"The guide index lists an id that is not a whole number ({str(guide_id)[:60]!r}); it cannot be loaded.")
            continue
        guide = archive.read_json(Archive.guide(guide_id))
        if not isinstance(guide, dict):
            problems.append(f"guide {guide_id}: the guide itself is missing or unreadable")
            continue
        if not isinstance(archive.read_json(Archive.guide_tags(guide_id)), list):
            problems.append(f"guide {guide_id}: its tags are missing")
        check_media(f"guide {guide_id}", guide)

    for namespace in manifest.get("namespaces") or []:
        try:
            listing = archive.read_json(Archive.wiki_index(namespace))
        except ArchiveError as error:
            problems.append(f"The manifest names a wiki namespace that cannot be one: {error}")
            continue
        for entry in listing if isinstance(listing, list) else []:
            stats["pages"] += 1
            if not isinstance(entry, dict) or not is_safe_id(entry.get("wikiid")):
                problems.append(f"The {namespace} page index holds an entry without a usable id; it cannot be loaded.")
                continue
            page = archive.read_json(Archive.wiki(namespace, entry.get("wikiid")))
            if not isinstance(page, dict):
                problems.append(f"{namespace} page “{entry.get('title')}”: missing or unreadable")
                continue
            check_media(f"{namespace} page “{entry.get('title')}”", page)

    return list(dict.fromkeys(problems)), stats


# ---------------------------------------------------------------- how old the copies are


@dataclass(frozen=True)
class Capture:
    """When one item of the archive was taken from the site, and last confirmed current."""

    key: str
    kind: str
    captured_at: datetime | None
    confirmed_at: datetime | None

    @property
    def as_of(self) -> datetime | None:
        """The latest moment the copy is known to have matched the site."""
        moments = [moment for moment in (self.captured_at, self.confirmed_at) if moment is not None]
        return max(moments) if moments else None


def parse_instant(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def captures(archive: Archive) -> list[Capture]:
    """Every exported item with its capture time, oldest first; undated ones lead."""
    found = [
        Capture(key, str(entry.get("kind")), parse_instant(entry.get("fetched_at")), parse_instant(entry.get("confirmed_at")))
        for key, entry in archive.manifest()["items"].items()
        if isinstance(entry, dict) and entry.get("status") == "ok"
    ]
    return sorted(found, key=lambda capture: (capture.as_of or datetime.min.replace(tzinfo=timezone.utc), capture.key))


def age_text(moment: datetime | None, now: datetime) -> str:
    if moment is None:
        return "at an unrecorded time"
    days = (now - moment).total_seconds() / 86400
    if days < 1:
        return "today" if days >= 0 else "in the future (check the clock)"
    return f"{int(days)} day{'s' if int(days) != 1 else ''} ago"


RECHECKED_KINDS = {
    "guide": "compared with the site's listing on every run",
    "guide-tags": "fetched again whenever its guide changed",
    "wiki": "compared with the site's listing on every run",
    "wiki-tags": "fetched again whenever its page changed",
    "image-meta": "fetched again only when a guide or page using the image changed, or with --refresh",
    "image-file": "downloaded again only when its metadata changed",
    "video-meta": "not checked again unless --refresh",
    "video-file": "never downloaded again",
    "user": "not checked again unless --refresh",
    "category": "not checked again unless --refresh",
    "category-tree": "not checked again unless --refresh",
}


def capture_report(archive: Archive, now: datetime | None = None, every_item: bool = False) -> list[str]:
    """How old the archive's copies are, per kind, and optionally item by item.

    The age that matters is the time since a copy was last *known* to match the
    site: when it was fetched, or when a later run compared it with the site's
    listing and left it alone.
    """
    now = now or datetime.now(timezone.utc)
    by_kind: dict[str, list[Capture]] = {}
    for capture in captures(archive):
        by_kind.setdefault(capture.kind, []).append(capture)
    lines = ["Age of the copies (time since each was fetched, or last confirmed unchanged against the site):"]
    for kind, group in sorted(by_kind.items()):
        dated = [capture for capture in group if capture.as_of is not None]
        undated = len(group) - len(dated)
        if dated:
            oldest, newest = dated[0], dated[-1]
            span = f"oldest {age_text(oldest.as_of, now)} ({oldest.key}, {oldest.as_of:%Y-%m-%d}), newest {age_text(newest.as_of, now)}"
        else:
            span = "no capture time recorded"
        lines.append(
            f"  {kind + ':':<15}{len(group)} item{'s' if len(group) != 1 else ''}, {span}"
            + (f", {undated} without a recorded time" if undated and dated else "")
            + (f" — {RECHECKED_KINDS[kind]}" if kind in RECHECKED_KINDS else "")
        )
    if every_item:
        lines.append("Every item, oldest first:")
        for group in by_kind.values():
            for capture in group:
                detail = f"fetched {capture.captured_at:%Y-%m-%dT%H:%M:%SZ}" if capture.captured_at is not None else "fetch time not recorded"
                if capture.confirmed_at is not None:
                    detail += f", confirmed unchanged {capture.confirmed_at:%Y-%m-%dT%H:%M:%SZ}"
                lines.append(f"  {capture.key}: {detail} ({age_text(capture.as_of, now)})")
    return lines

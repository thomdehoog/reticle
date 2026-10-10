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

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import ARCHIVE_FORMAT, TOOL_NAME, TOOL_VERSION
from .archive import MANIFEST, Archive, ArchiveError, sha256_file
from .client import AuthenticationError, ClientError, DozukiClient, NotFound, path_segment
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
    return isinstance(value, dict) and isinstance(value.get("videoid"), int) and isinstance(value.get("encodings"), list)


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
    ) -> None:
        self.client = client
        self.archive = archive
        self.namespaces = tuple(namespace.upper() for namespace in namespaces)
        self.refresh = refresh
        self.log = log
        self.items: dict[str, dict[str, Any]] = {}
        self.warnings: list[str] = []
        self.started_at = utc_now()
        self.include_private = client.authenticated
        self._since_save = 0
        previous = archive.read_json(MANIFEST)
        if isinstance(previous, dict) and isinstance(previous.get("items"), dict):
            self.items = previous["items"]
            self.started_at = previous.get("started_at") or self.started_at

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
    ) -> Any:
        """Fetch one response and store it raw, or take it from disk if it is there.

        ``optional`` marks something that may legitimately not exist (a category
        with no page, a namespace the site does not use): its absence is noted
        and is not a failure.
        """
        if reuse and not self.refresh and self.archive.exists(relative):
            stored = self.archive.read_json(relative)
            if stored is not None:
                previous = self.items.get(key, {})
                self.record(key, kind, "ok", path=relative, fetched_at=previous.get("fetched_at"), bytes=previous.get("bytes"))
                return stored
        try:
            document, body = self.client.get(path, params)
        except AuthenticationError:
            raise
        except NotFound as error:
            self.record(key, kind, "absent" if optional else "failed", error=None if optional else str(error))
            return None
        except ClientError as error:
            self.record(key, kind, "failed", error=str(error))
            return None
        self.archive.write_raw(relative, body)
        self.record(key, kind, "ok", path=relative, fetched_at=utc_now(), bytes=len(body))
        return document

    def pages(self, path: str, params: dict[str, Any], identity: Callable[[Any], Any]) -> list[Any]:
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
                    batch, _ = self.client.get(path, {**params, "limit": size, "offset": page * size})
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
                if marker in seen:
                    continue
                seen.add(marker)
                collected.append(entry)
                fresh += 1
            if fresh == 0:
                break
        return collected

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
            guides = stored if isinstance(stored, list) else []
            if guides:
                self.warn("The guide list could not be fetched; continuing with the list from the previous run.")
        else:
            guides = [entry for entry in guides if isinstance(entry, dict) and entry.get("guideid") is not None]
            previous = self.archive.read_json(Archive.guide_index())
            known = {entry.get("guideid") for entry in guides}
            if isinstance(previous, list):
                kept = [entry for entry in previous if isinstance(entry, dict) and entry.get("guideid") not in known]
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
            )
            self.fetch(f"guide-tags:{guide_id}", "guide-tags", f"/guides/{guide_id}/tags", Archive.guide_tags(guide_id), reuse=current)
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
            listing = stored if isinstance(stored, list) else []
        else:
            listing = [entry for entry in listing if isinstance(entry, dict) and entry.get("wikiid") is not None and entry.get("title")]
            if namespace == "CATEGORY":
                listing.extend(self._unlisted_category_pages({entry["wikiid"] for entry in listing}))
            self.archive.write_json(Archive.wiki_index(namespace), listing)
            self.record(key, "wiki-index", "ok", path=Archive.wiki_index(namespace), fetched_at=utc_now(), count=len(listing))

        for entry in listing:
            wiki_id, title = entry["wikiid"], str(entry["title"])
            stored = self.archive.read_json(Archive.wiki(namespace, wiki_id))
            current = isinstance(stored, dict) and stored.get("revisionid") == entry.get("revisionid")
            segment = path_segment(title)
            self.fetch(f"wiki:{namespace}:{wiki_id}", "wiki", f"/wikis/{namespace}/{segment}", Archive.wiki(namespace, wiki_id), reuse=current)
            self.fetch(
                f"wiki-tags:{namespace}:{wiki_id}", "wiki-tags", f"/wikis/{namespace}/{segment}/tags",
                Archive.wiki_tags(namespace, wiki_id), optional=True, reuse=current,
            )

    def _unlisted_category_pages(self, listed: set[Any]) -> list[dict[str, Any]]:
        """Index entries for category pages the wiki listing leaves out.

        Every category is a wiki page, but the listing was seen to return fewer
        titles than there are categories — the holding categories among them.
        Their pages are asked for by title, and those that exist join the index.
        """
        extra: list[dict[str, Any]] = []
        for path in sorted(self.archive.path("api/categories/detail").glob("*.json")):
            detail = self.archive.read_json(str(path.relative_to(self.archive.root)))
            if not isinstance(detail, dict):
                continue
            wiki_id, title = detail.get("wikiid"), detail.get("wiki_title")
            if not isinstance(wiki_id, int) or not isinstance(title, str) or not title or wiki_id in listed:
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
                    }
                )
        return extra

    # ------------------------------------------------------------ media

    def stored_documents(self) -> Iterator[Any]:
        """Every content response on disk whose media the export must hold."""
        for path in sorted(self.archive.path("api").glob("guides/*/guide.json")):
            yield self.archive.read_json(str(path.relative_to(self.archive.root)))
        for path in sorted(self.archive.path("api").glob("wikis/*/*.json")):
            if path.name != "index.json" and not path.name.endswith(".tags.json"):
                yield self.archive.read_json(str(path.relative_to(self.archive.root)))
        for path in sorted(self.archive.path("api").glob("wikis/*/index.json")):
            yield self.archive.read_json(str(path.relative_to(self.archive.root)))
        for path in sorted(self.archive.path("api").glob("categories/detail/*.json")):
            document = self.archive.read_json(str(path.relative_to(self.archive.root)))
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
            meta = self.fetch(f"image-meta:{image_id}", "image-meta", f"/media/images/{image_id}", Archive.image_meta(image_id))
            self.download_image(image_id, meta if isinstance(meta, dict) else {}, images.get(image_id) or {})
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
        for path in sorted(self.archive.path(folder).glob(f"{vendor_id}.*")):
            if path.suffix in {".part", ".download", ".tmp"}:
                continue
            relative = str(path.relative_to(self.archive.root))
            self.record(key, kind, "ok", path=relative, sha256=sha256_file(path), bytes=path.stat().st_size, adopted=True)
            return True
        return False

    def _download(self, key: str, kind: str, folder: str, vendor_id: int, url: str, extension: Callable[[str], str], **fields: Any) -> None:
        temporary = self.archive.path(f"{folder}/{vendor_id}.download")
        try:
            result = self.client.download(url, temporary)
        except AuthenticationError:
            raise
        except ClientError as error:
            self.record(key, kind, "failed", error=str(error), url=url)
            return
        relative = f"{folder}/{vendor_id}.{extension(result.content_type)}"
        temporary.replace(self.archive.path(relative))
        self.record(
            key, kind, "ok", path=relative, sha256=result.sha256, bytes=result.size, url=url,
            content_type=result.content_type or None, fetched_at=utc_now(), **fields,
        )

    def download_image(self, image_id: int, meta: dict[str, Any], embedded: dict[str, Any]) -> None:
        key = f"image-file:{image_id}"
        if self._already_downloaded(key, "image-file", "files/images", image_id):
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

        self._download(key, "image-file", "files/images", image_id, url, extension, rendition=rendition)

    def download_video(self, video_id: int, video: dict[str, Any]) -> None:
        key = f"video-file:{video_id}"
        if self._already_downloaded(key, "video-file", "files/videos", video_id):
            return
        encoding = best_encoding(video)
        if encoding is None:
            self.record(key, "video-file", "failed", error="the video offers no encoding to download")
            return
        self._download(
            key, "video-file", "files/videos", video_id, encoding["url"], lambda _content_type: encoding_extension(encoding),
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
    items: dict[str, Any] = manifest["items"]

    if not manifest.get("finished_at"):
        problems.append("The export did not run to completion (no finished_at in the manifest); run it again to resume.")
    for key, entry in sorted(items.items()):
        if entry.get("status") == "failed":
            problems.append(f"{key}: failed during export — {entry.get('error', 'no reason recorded')}")

    for key, entry in sorted(items.items()):
        if entry.get("status") != "ok" or not entry.get("path"):
            continue
        path = archive.path(entry["path"])
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
        guide = archive.read_json(Archive.guide(guide_id))
        if not isinstance(guide, dict):
            problems.append(f"guide {guide_id}: the guide itself is missing or unreadable")
            continue
        if not isinstance(archive.read_json(Archive.guide_tags(guide_id)), list):
            problems.append(f"guide {guide_id}: its tags are missing")
        check_media(f"guide {guide_id}", guide)

    for namespace in manifest.get("namespaces") or []:
        listing = archive.read_json(Archive.wiki_index(namespace))
        for entry in listing if isinstance(listing, list) else []:
            stats["pages"] += 1
            page = archive.read_json(Archive.wiki(namespace, entry.get("wikiid")))
            if not isinstance(page, dict):
                problems.append(f"{namespace} page “{entry.get('title')}”: missing or unreadable")
                continue
            check_media(f"{namespace} page “{entry.get('title')}”", page)

    return list(dict.fromkeys(problems)), stats

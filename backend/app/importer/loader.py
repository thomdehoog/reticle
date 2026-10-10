"""Phase two: read an export archive and write it into Reticle.

Nothing here talks to the vendor; the archive on disk is the only input, so a
load can be repeated for as long as the archive is kept. And nothing here
writes SQL of its own: guides go through ``documents.apply_document``, pages
through ``pages.apply_document``, images through ``images.normalise``, videos
through ``videos.sniff`` and ``videos.store``, tags through the application's
slug rule, and a published item gets its snapshot from ``content``. Imported
content is therefore held to exactly the rules of content typed into the
editor, and cannot arrive in a shape the application would not itself produce.

The run is a sequence of small transactions — one for the categories, then one
per guide and one per page — so a single bad item is reported and skipped
instead of ending the import. ``ImportRecord`` rows remember which vendor item
became which row, which is what makes a second run an update and lets it leave
alone anything a colleague has edited in Reticle since.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from .. import audit, content, errors, images, videos
from .. import pages as page_documents
from ..db import utcnow
from ..documents import apply_document as apply_guide_document
from ..models import PUBLISHED, Category, Guide, ImportRecord, Media, Page, User, new_id
from ..routers.guides import GUIDES
from ..routers.pages import PAGES
from ..schemas import (
    MAX_BULLETS_PER_STEP,
    MAX_PAGE_BODY_CHARS,
    MAX_TAG_LENGTH,
    MAX_TAGS_PER_GUIDE,
    AnnotationIn,
    BulletIn,
    GuideDocumentIn,
    MediaRefIn,
    PageDocumentIn,
    StepIn,
)
from ..settings import Settings
from ..slugs import slugify, tag_slug, unique_slug
from . import TOOL_NAME, TOOL_VERSION, mapping, markers
from .archive import Archive, filename_title
from .exporter import category_titles, is_image_object, is_video_object
from .report import Report
from .wikitext import Conversion, LinkResolver, Target, html_to_plain, referenced_image_ids, to_markdown, to_plain

MAPPING_VERSION = 1
"""Part of every fingerprint: raise it when the mapping changes, and the next
load rewrites content that the vendor has not touched."""

UNUSABLE_PASSWORD_HASH = "!imported-account-no-password"
"""Not an Argon2 hash, so no password can ever verify against it.

Authors who have no Reticle account are created so that attribution survives,
but inactive and with this in place of a hash: the import must not mint logins.
"""

PLACEHOLDER_EMAIL_DOMAIN = "import.invalid"
DEFAULT_LOAD_NAMESPACES = ("CATEGORY", "WIKI", "ITEM")
"""``INFO`` is left out on purpose: on a vendor site that namespace holds the
vendor's own boilerplate (FAQ and flag descriptions), which is not the
facility's content and must not be copied into Reticle. See ``NOTICE.md``."""

ROOT_CATEGORY = "root"
UNCATEGORISED = "Imported – uncategorised"
VOLATILE_KEYS = frozenset(
    {
        "can_edit", "can_delete", "can_edit_language", "can_edit_permissions", "should_use_granular_permissions",
        "favorited", "completed", "patrol_threshold", "comments", "editUrl", "createApprovalsURL",
        "can_set_approval_processes", "permissions",
    }
)
"""Fields that describe the caller rather than the content.

Left out of the fingerprint so that exporting again from a different account
does not make every guide look modified.
"""

SUMMARY_LIMIT = 4000
PROSE_LIMIT = 20_000
TITLE_LIMIT = 240
STEP_TITLE_LIMIT = 400
BULLET_LIMIT = 4000
CATEGORY_NAME_LIMIT = 200
CATEGORY_DESCRIPTION_LIMIT = 2000
SHRINK_PIXEL_ALLOWANCE = 250_000_000
PROGRESS_EVERY = 25


class LoadError(Exception):
    """The load cannot start at all."""


class Skip(Exception):
    """Leave this item as it is; the message says why."""


@dataclass(frozen=True)
class LoadOptions:
    publish: bool = True
    dry_run: bool = False
    force: bool = False
    owner_email: str | None = None
    markers: str = "auto"
    arrow_head: str = "auto"
    namespaces: tuple[str, ...] = DEFAULT_LOAD_NAMESPACES
    only_guides: frozenset[int] | None = None


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(child) for key, child in sorted(value.items()) if key not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_stable(child) for child in value]
    return value


def fingerprint(*parts: Any) -> str:
    payload = json.dumps([_stable(part) for part in parts], sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


class Loader:
    def __init__(
        self,
        session: DbSession,
        archive: Archive,
        options: LoadOptions,
        settings: Settings,
        log: Callable[[str], None] = print,
    ) -> None:
        self.db = session
        self.archive = archive
        self.options = options
        self.settings = settings
        self.log = log
        self.report = Report()
        self.manifest = archive.manifest()
        self.source = str(self.manifest.get("site") or "unknown")
        self.resolver = LinkResolver(site_hosts=frozenset({self.source.lower()}))
        self.categories: dict[str, str] = {}
        self.display_titles: dict[str, str] = {}
        self.guide_slugs: dict[int, str] = {}
        self.page_slugs: dict[tuple[str, int], str] = {}
        self.users: dict[str, str] = {}
        self.owner_id: str | None = None
        self.tag_spellings: dict[str, set[str]] = {}
        self._written: list[Path] = []
        self._undo: list[Callable[[], None]] = []

    # ------------------------------------------------------------ transactions

    @contextmanager
    def item(self, kind: str, reference: str) -> Iterator[None]:
        """One item, one transaction.

        A failure rolls back to the savepoint, removes any media file the item
        had already put on disk and is recorded; the run goes on. In a dry run
        nothing is ever committed, and the whole session is rolled back at the
        end.
        """
        self._written = []
        self._undo = []
        savepoint = self.db.begin_nested()
        try:
            yield
            self.db.flush()
        except Skip as skip:
            self._abandon(savepoint)
            self.report.add(kind, reference, "skipped", str(skip))
        except Exception as problem:  # noqa: BLE001 - one bad item must not end the import
            self._abandon(savepoint)
            self.report.add(kind, reference, "failed", self._explain(problem))
            self.log(f"  FAILED {kind} {reference}: {self._explain(problem)}")
        else:
            savepoint.commit()
            if not self.options.dry_run:
                self.db.commit()

    def _abandon(self, savepoint: Any) -> None:
        savepoint.rollback()
        for path in self._written:
            path.unlink(missing_ok=True)
        for undo in reversed(self._undo):
            undo()
        self.db.expire_all()

    @staticmethod
    def _explain(problem: Exception) -> str:
        if isinstance(problem, errors.ApiError):
            return problem.message
        if isinstance(problem, ValidationError):
            first = problem.errors()[0]
            where = ".".join(str(part) for part in first.get("loc", ()))
            return f"the converted document is not valid ({where}: {first.get('msg')})"
        return f"{type(problem).__name__}: {problem}"

    def _remember(self, store: dict, key: Any, value: Any) -> None:
        """Cache something for the rest of the run, undone if the item fails."""
        store[key] = value
        self._undo.append(lambda: store.pop(key, None))

    # ------------------------------------------------------------ records

    def record(self, kind: str, vendor_id: Any) -> ImportRecord | None:
        return self.db.scalars(
            select(ImportRecord).where(
                ImportRecord.source == self.source, ImportRecord.kind == kind, ImportRecord.vendor_id == str(vendor_id)
            )
        ).one_or_none()

    def remember(self, kind: str, vendor_id: Any, reticle_id: str, mark: str = "", updated_at: datetime | None = None) -> None:
        record = self.record(kind, vendor_id)
        if record is None:
            record = ImportRecord(source=self.source, kind=kind, vendor_id=str(vendor_id))
            self.db.add(record)
        record.reticle_id = reticle_id
        record.fingerprint = mark
        record.imported_updated_at = updated_at
        self.db.flush()

    # ------------------------------------------------------------ the run

    def run(self) -> Report:
        options = self.options
        self.report.header = {
            "Archive": str(self.archive.root),
            "Source site": self.source,
            "Exported": str(self.manifest.get("finished_at") or self.manifest.get("updated_at") or "unknown")
            + ("" if self.manifest.get("authenticated") else " (anonymously: public content only)"),
            "Loaded": utcnow().isoformat(timespec="seconds"),
            "Mode": ("DRY RUN — nothing was written" if options.dry_run else "live")
            + (", public content published" if options.publish else ", everything as drafts")
            + (", --force" if options.force else ""),
            "Markers": "burned into the images" if options.markers == "burned" else "converted to annotations where the pixels confirm them",
            "Tool": f"{TOOL_NAME} {TOOL_VERSION}",
        }
        if not self.manifest.get("finished_at"):
            self.report.note("The export did not run to completion; this load covers only what the archive holds.")
        try:
            self._resolve_owner()
            with self.item("categories", "category tree"):
                self.load_categories()
            if self.report.failed:
                raise LoadError(f"The categories could not be created ({self.report.failed[0].detail}); nothing else was attempted.")
            self.plan_slugs()
            self.load_guides()
            self.load_pages()
            self._closing_notes()
        finally:
            if options.dry_run:
                self.db.rollback()
        return self.report

    def _resolve_owner(self) -> None:
        if not self.options.owner_email:
            return
        email = self.options.owner_email.strip().lower()
        owner = self.db.scalars(select(User).where(User.email == email)).one_or_none()
        if owner is None:
            raise LoadError(
                f"--owner-email {email} is not an existing Reticle account. Create it first, or leave the option "
                "out to keep the original authors."
            )
        self.owner_id = owner.id
        self.report.note(f"All imported content is owned by {email} (--owner-email); original authors are not recorded.")

    # ------------------------------------------------------------ people

    def user_for(self, vendor_user_id: Any, fallback_name: str = "") -> User:
        """The Reticle account that stands for a vendor author."""
        if self.owner_id is not None:
            return self.db.get(User, self.owner_id)

        user_id = _positive_int(vendor_user_id)
        key = str(user_id) if user_id is not None else "unknown"
        if key in self.users:
            return self.db.get(User, self.users[key])

        record = self.record("user", key)
        user = self.db.get(User, record.reticle_id) if record is not None else None
        if user is None:
            profile = self.archive.read_json(Archive.user(user_id)) if user_id is not None else None
            profile = profile if isinstance(profile, dict) else {}
            email = _text(profile.get("login")).strip().lower()
            name = _text(profile.get("username")).strip() or fallback_name.strip() or _text(profile.get("unique_username")).strip()

            if user_id is None:
                email, name = f"imported-content@{PLACEHOLDER_EMAIL_DOMAIN}", "Imported content"
            elif "@" not in email:
                email = f"dozuki-user-{user_id}@{PLACEHOLDER_EMAIL_DOMAIN}"
                self.report.warn(
                    "author", f"user {user_id}", f"No e-mail address in the archive for “{name or user_id}”; a placeholder account stands in."
                )

            user = self.db.scalars(select(User).where(User.email == email)).one_or_none()
            if user is None:
                user = User(
                    email=email,
                    display_name=(name or f"Imported user {key}")[:200],
                    role="viewer",
                    password_hash=UNUSABLE_PASSWORD_HASH,
                    is_active=False,
                )
                self.db.add(user)
                self.db.flush()
                self.report.add("user", f"{user.display_name} <{email}>", "created", "inactive, no password: attribution only")
            self.remember("user", key, user.id)
        self._remember(self.users, key, user.id)
        return user

    # ------------------------------------------------------------ categories

    def _category_facts(self) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Every category the archive knows of, with what is known about each."""
        facts: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        def know(title: Any) -> dict[str, Any]:
            title = str(title)
            if title not in facts:
                facts[title] = {"display": None, "parent": None, "description": "", "children": [], "ancestors": []}
                order.append(title)
            return facts[title]

        hierarchy = self.archive.read_json("api/categories/hierarchy.json")
        hierarchy = hierarchy if isinstance(hierarchy, dict) else {}
        for tree in (self.archive.read_json("api/categories/tree.json"), hierarchy.get("hierarchy")):
            for title, parent in category_titles(tree):
                entry = know(title)
                if parent is not None and entry["parent"] is None:
                    entry["parent"] = parent
        for title, display in (hierarchy.get("display_titles") or {}).items() if isinstance(hierarchy.get("display_titles"), dict) else []:
            know(title)["display"] = _text(display) or None

        flat = self.archive.read_json("api/categories/all.json")
        for title in flat if isinstance(flat, list) else []:
            if isinstance(title, str):
                know(title)

        for path in sorted(self.archive.path("api/categories/detail").glob("*.json")):
            detail = self.archive.read_json(str(path.relative_to(self.archive.root)))
            if not isinstance(detail, dict):
                continue
            entry = know(_text(detail.get("wiki_title")) or filename_title(path.stem))
            entry["display"] = _text(detail.get("display_title")) or entry["display"]
            entry["description"] = _text(detail.get("description"))
            entry["children"] = [child for child in detail.get("children") or [] if isinstance(child, str)]
            entry["ancestors"] = [ancestor for ancestor in detail.get("ancestors") or [] if isinstance(ancestor, str)]

        listing = self.archive.read_json(Archive.wiki_index("CATEGORY"))
        for item in listing if isinstance(listing, list) else []:
            if isinstance(item, dict) and item.get("title"):
                entry = know(item["title"])
                entry["display"] = entry["display"] or _text(item.get("display_title")) or None

        for guide in self._guide_index():
            for candidate in (guide.get("category"), (self.archive.read_json(Archive.guide(guide["guideid"])) or {}).get("category")):
                if isinstance(candidate, str) and candidate.strip():
                    know(candidate)
        return facts, order

    def _parents(self, facts: dict[str, dict[str, Any]]) -> dict[str, str | None]:
        """Each category's parent title, from the tree first and the details second."""
        by_display: dict[str, list[str]] = {}
        for title, entry in facts.items():
            by_display.setdefault((entry["display"] or title).casefold(), []).append(title)

        def by_name(name: str) -> str | None:
            if name in facts:
                return name
            matches = by_display.get(name.casefold(), [])
            return matches[0] if len(matches) == 1 else None

        parents: dict[str, str | None] = {title: entry["parent"] for title, entry in facts.items()}
        for title, entry in facts.items():
            for child_name in entry["children"]:
                child = by_name(child_name)
                if child is not None and child != title and parents.get(child) is None:
                    parents[child] = title
        for title, entry in facts.items():
            if parents[title] is None and entry["ancestors"]:
                parent = by_name(entry["ancestors"][0])
                if parent is not None and parent != title:
                    parents[title] = parent

        for title in facts:
            seen = {title}
            cursor = parents[title]
            while cursor is not None:
                if cursor in seen or cursor not in facts:
                    parents[title] = None
                    break
                seen.add(cursor)
                cursor = parents[cursor]
            if parents[title] is not None and parents[title].casefold() == ROOT_CATEGORY:
                parents[title] = None
        return parents

    def load_categories(self) -> None:
        facts, order = self._category_facts()
        parents = self._parents(facts)
        reserved: set[str] = set()
        position = self.db.scalar(select(func.coalesce(func.max(Category.order_index), -1))) + 1

        def ensure(title: str) -> str | None:
            nonlocal position
            if title.casefold() == ROOT_CATEGORY:
                return None
            if title in self.categories:
                return self.categories[title]
            entry = facts[title]
            display = (entry["display"] or title).strip() or title
            self.display_titles[title] = display
            parent_title = parents[title]
            parent_id = ensure(parent_title) if parent_title is not None else None

            record = self.record("category", title)
            category = self.db.get(Category, record.reticle_id) if record is not None else None
            reference = f"“{display}”" + (f" (internal title “{title}”)" if display != title else "")
            if category is not None:
                self.report.add("category", reference, "unchanged")
            else:
                hidden = mapping.is_hidden_category(title, display)
                category = self.db.scalars(
                    select(Category).where(func.lower(Category.name) == display.lower()).order_by(Category.created_at)
                ).first()
                if category is not None and self.record_for_reticle("category", category.id) is None:
                    self.report.add("category", reference, "unchanged")
                    self.report.note(f"Category {reference} matched an existing Reticle category of the same name and was reused.")
                else:
                    name, clipped = mapping.clip(display, CATEGORY_NAME_LIMIT)
                    if clipped:
                        self.report.warn("clipped", f"category {reference}", "Name shortened to 200 characters.")
                    category = Category(
                        slug=unique_slug(display, lambda slug: slug in reserved or self._slug_taken(Category, slug), fallback="category"),
                        name=name,
                        description=mapping.clip(entry["description"], CATEGORY_DESCRIPTION_LIMIT)[0],
                        parent_id=parent_id,
                        order_index=position,
                        is_hidden=hidden,
                    )
                    position += 1
                    reserved.add(category.slug)
                    self.db.add(category)
                    self.db.flush()
                    self.report.add("category", reference, "created", "hidden holding category" if hidden else "")
                self.remember("category", title, category.id)
            self.categories[title] = category.id
            self.resolver.add_wiki("CATEGORY", title, Target(f"/c/{category.slug}", category.name))
            return category.id

        for title in order:
            ensure(title)

    def record_for_reticle(self, kind: str, reticle_id: str) -> ImportRecord | None:
        return self.db.scalars(
            select(ImportRecord).where(
                ImportRecord.source == self.source, ImportRecord.kind == kind, ImportRecord.reticle_id == reticle_id
            )
        ).first()

    def _slug_taken(self, model: type, slug: str) -> bool:
        return self.db.scalar(select(func.count()).select_from(model).where(model.slug == slug)) > 0

    def _uncategorised(self) -> str:
        """A holding category for guides whose own category is not in the archive."""
        if UNCATEGORISED not in self.categories:
            record = self.record("category", UNCATEGORISED)
            category = self.db.get(Category, record.reticle_id) if record is not None else None
            if category is None:
                category = Category(
                    slug=unique_slug(UNCATEGORISED, lambda slug: self._slug_taken(Category, slug)),
                    name=UNCATEGORISED,
                    description="Guides whose category on the old site could not be determined.",
                    order_index=self.db.scalar(select(func.coalesce(func.max(Category.order_index), -1))) + 1,
                    is_hidden=True,
                )
                self.db.add(category)
                self.db.flush()
                self.remember("category", UNCATEGORISED, category.id)
            self._remember(self.categories, UNCATEGORISED, category.id)
        return self.categories[UNCATEGORISED]

    # ------------------------------------------------------------ planning

    def _guide_index(self) -> list[dict[str, Any]]:
        index = self.archive.read_json(Archive.guide_index())
        entries = [entry for entry in index if isinstance(entry, dict) and _positive_int(entry.get("guideid"))] if isinstance(index, list) else []
        return sorted(entries, key=lambda entry: entry["guideid"])

    def _wiki_index(self) -> list[tuple[str, dict[str, Any]]]:
        entries: list[tuple[str, dict[str, Any]]] = []
        for namespace in self.options.namespaces:
            listing = self.archive.read_json(Archive.wiki_index(namespace))
            for entry in listing if isinstance(listing, list) else []:
                if isinstance(entry, dict) and _positive_int(entry.get("wikiid")) and entry.get("title"):
                    entries.append((namespace, entry))
        return entries

    def plan_slugs(self) -> None:
        """Give every guide and page its Reticle address before any text is converted.

        A guide may link to one that is imported after it, so the addresses have
        to exist first. Items imported on an earlier run keep the slug they have.
        """
        reserved: set[str] = set()
        for entry in self._guide_index():
            guide_id = entry["guideid"]
            payload = self.archive.read_json(Archive.guide(guide_id))
            title = self._guide_title(guide_id, payload if isinstance(payload, dict) else entry)
            record = self.record("guide", guide_id)
            existing = self.db.get(Guide, record.reticle_id) if record is not None else None
            if existing is not None:
                slug = existing.slug
            else:
                slug = unique_slug(title, lambda slug: slug in reserved or self._slug_taken(Guide, slug), fallback="guide")
                reserved.add(slug)
            self.guide_slugs[guide_id] = slug
            self.resolver.guides[guide_id] = Target(f"/g/{slug}", title)

        reserved = set()
        for namespace, entry in self._wiki_index():
            wiki_id = entry["wikiid"]
            title = self._page_title(entry)
            record = self.record("wiki", wiki_id)
            existing = self.db.get(Page, record.reticle_id) if record is not None else None
            if existing is not None:
                slug = existing.slug
            else:
                slug = unique_slug(title, lambda slug: slug in reserved or self._slug_taken(Page, slug), fallback="page")
                reserved.add(slug)
            self.page_slugs[(namespace, wiki_id)] = slug
            if namespace != "CATEGORY" or str(entry["title"]) not in self.categories:
                self.resolver.add_wiki(namespace, str(entry["title"]), Target(f"/w/{slug}", title))

    @staticmethod
    def _guide_title(guide_id: int, payload: dict[str, Any]) -> str:
        return " ".join(_text(payload.get("title")).split()) or f"Untitled guide {guide_id}"

    @staticmethod
    def _page_title(entry: dict[str, Any]) -> str:
        return " ".join((_text(entry.get("display_title")) or _text(entry.get("title"))).split()) or f"Untitled page {entry.get('wikiid')}"

    # ------------------------------------------------------------ media

    @staticmethod
    def _open(path: Path) -> tuple[Image.Image, bool]:
        """A picture as a browser would show it, and whether its format is lossless.

        Decoded with EXIF rotation applied. The pixel ceiling is raised for the
        duration: this is the facility's own archive rather than an upload from
        the network, and a picture too large for Reticle is opened here only to
        be scaled down.
        """
        previous = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = SHRINK_PIXEL_ALLOWANCE
        try:
            with Image.open(path) as handle:
                lossless = (handle.format or "").upper() != "JPEG"
                handle.load()
                return ImageOps.exif_transpose(handle), lossless
        finally:
            Image.MAX_IMAGE_PIXELS = previous

    def _encode(self, picture: Image.Image, lossless: bool) -> bytes:
        """Encode for storage, shrinking until the result fits Reticle's limits.

        A screenshot stays PNG, because JPEG smears text; a photograph stays
        JPEG. A picture too large for the application to accept is scaled down
        rather than left out: a smaller picture is worth more than a missing one.
        """
        settings = self.settings
        while True:
            width, height = picture.size
            scale = min(1.0, settings.max_image_dimension / max(width, height), (settings.max_image_pixels / (width * height)) ** 0.5)
            if scale < 1.0:
                picture = picture.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            if lossless:
                picture.save(buffer, format="PNG", optimize=True)
            else:
                picture.convert("RGB").save(buffer, format="JPEG", quality=92)
            if buffer.tell() <= settings.max_upload_bytes or max(picture.size) <= 256:
                return buffer.getvalue()
            lossless = False
            picture = picture.resize((max(1, picture.size[0] * 3 // 4), max(1, picture.size[1] * 3 // 4)), Image.Resampling.LANCZOS)

    def _store_image(
        self,
        reference: str,
        record_key: str,
        label: str,
        actor: User,
        *,
        path: Path | None = None,
        picture: Image.Image | None = None,
        lossless: bool = True,
        mark: str = "",
    ) -> Media:
        """Store one picture as an upload would be stored, once per vendor image.

        The file goes through ``images.normalise`` like any upload. If the
        application refuses it as it is — too many bytes or pixels, a format it
        does not take, an EXIF rotation it would drop — it is decoded and
        re-encoded here first, and the report says so.
        """
        record = self.record("image", record_key)
        if record is not None and record.fingerprint == mark:
            media = self.db.get(Media, record.reticle_id)
            if media is not None and (self.options.dry_run or (self.settings.media_root / media.storage_path).is_file()):
                return media

        settings = self.settings
        normalised: images.NormalisedImage | None = None
        reason = ""
        if picture is None:
            with Image.open(path) as probe:
                rotated = probe.getexif().get(0x0112, 1) not in (None, 1)
            if rotated:
                reason = "its EXIF rotation was applied"
            elif path.stat().st_size > settings.max_upload_bytes:
                reason = "the file is larger than the upload limit"
            else:
                try:
                    normalised = images.normalise(path.read_bytes(), settings.max_image_dimension, settings.max_image_pixels)
                except errors.ApiError as refusal:
                    reason = refusal.message
            if normalised is None:
                picture, lossless = self._open(path)
        if normalised is None:
            normalised = images.normalise(self._encode(picture, lossless), settings.max_image_dimension, settings.max_image_pixels)
            if reason and "EXIF" not in reason:
                self.report.warn("marker_note", reference, f"{label} was re-encoded to fit Reticle’s limits ({reason})")

        media_id = new_id()
        storage_path = images.relative_storage_path(media_id, normalised.extension)
        if not self.options.dry_run:
            self._written.append(images.write_file(settings.media_root, storage_path, normalised.payload))
        media = Media(
            id=media_id,
            kind="image",
            storage_path=storage_path,
            content_type=normalised.content_type,
            byte_size=len(normalised.payload),
            width=normalised.width,
            height=normalised.height,
            alt="",
            original_filename=f"dozuki-image-{slugify(record_key)}.{normalised.extension}",
            uploaded_by_id=actor.id,
        )
        self.db.add(media)
        self.db.flush()
        self.remember("image", record_key, media.id, mark)
        return media

    def plain_image(self, reference: str, image_id: int, actor: User) -> Media | None:
        """A vendor image exactly as the vendor showed it (markers, if any, burned in)."""
        path = self.archive.media_file("image", image_id)
        if path is None:
            self.report.warn("missing_media", reference, f"Image {image_id} is not in the archive.")
            return None
        try:
            return self._store_image(reference, str(image_id), f"Image {image_id}", actor, path=path)
        except Exception as problem:  # noqa: BLE001 - Pillow raises many things for a damaged file
            self.report.warn("missing_media", reference, f"Image {image_id} could not be imported: {self._explain(problem)}")
            return None

    def step_image(self, reference: str, image_id: int, actor: User, own_copy: bool = False) -> tuple[Media, list[dict[str, Any]]] | None:
        """An image for a step: the clean source plus annotations where that is safe.

        ``own_copy`` stores the clean picture as an upload of its own. Two
        marked-up versions of one photograph normally share a single clean
        upload, but a step cannot show the same upload twice.
        """
        meta = self.archive.read_json(Archive.image_meta(image_id))
        plan = markers.interpret(meta) if isinstance(meta, dict) else markers.Plan()

        if plan.has_markers and self.options.markers == "auto":
            reason = plan.fallback_reason
            if reason is None:
                try:
                    converted = self._annotated(reference, image_id, meta, plan, actor, own_copy)
                except Exception as problem:  # noqa: BLE001 - Pillow raises many things for a damaged file
                    converted, reason = None, f"the clean source could not be processed ({self._explain(problem)})"
                else:
                    if isinstance(converted, str):
                        converted, reason = None, converted
                if converted is not None:
                    return converted
            self.report.warn(
                "fallback_image", reference, f"Image {image_id}: {reason}. The marked-up picture is used as it is."
            )

        media = self.plain_image(reference, image_id, actor)
        return (media, []) if media is not None else None

    def _annotated(
        self, reference: str, image_id: int, meta: dict[str, Any], plan: markers.Plan, actor: User, own_copy: bool
    ) -> tuple[Media, list[dict[str, Any]]] | str:
        source_id = meta["srcid"]
        clean_path = self.archive.media_file("image", source_id)
        burned_path = self.archive.media_file("image", image_id)
        if clean_path is None:
            return f"its clean source image {source_id} is not in the archive"
        if burned_path is None:
            return "the marked-up picture itself is not in the archive, so the markers cannot be checked"

        clean, lossless = self._open(clean_path)
        info = meta["srcImageInfo"]
        if abs(clean.size[0] - float(info["width"])) > 1.5 or abs(clean.size[1] - float(info["height"])) > 1.5:
            return (
                f"the clean source file is {clean.size[0]}×{clean.size[1]} but the metadata says "
                f"{info['width']}×{info['height']}, so marker positions cannot be trusted"
            )
        realised = markers.realise(plan, clean, self._open(burned_path)[0], self.options.arrow_head)
        if realised is None:
            return "the converted markers do not line up with the markers visible in the picture"

        box = realised.image.size
        if realised.cropped:
            media = self._store_image(
                reference, f"{image_id}:clean", f"Image {image_id}", actor,
                picture=realised.image, lossless=lossless, mark=f"crop:{box[0]}x{box[1]}:{realised.label}",
            )
        else:
            key = f"{image_id}:clean" if own_copy else str(source_id)
            media = self._store_image(reference, key, f"Image {source_id}", actor, path=clean_path)
        for note in plan.notes + realised.notes:
            self.report.warn("marker_note", reference, f"Image {image_id}: {note}")
        annotations = [{"id": new_id(), **annotation} for annotation in realised.annotations]
        return media, annotations

    def video(self, reference: str, video_id: int, actor: User) -> Media | None:
        record = self.record("video", video_id)
        if record is not None:
            media = self.db.get(Media, record.reticle_id)
            if media is not None and (self.options.dry_run or (self.settings.media_root / media.storage_path).is_file()):
                return media

        path = self.archive.media_file("video", video_id)
        if path is None:
            self.report.warn("missing_media", reference, f"Video {video_id} is not in the archive.")
            return None
        with path.open("rb") as stream:
            video_format = videos.sniff(stream.read(videos.SNIFF_BYTES))
            if video_format is None:
                self.report.warn(
                    "missing_media", reference, f"Video {video_id} is not an MP4 or WebM file a browser can play; it was left out."
                )
                return None
            stream.seek(0)
            media_id = new_id()
            storage_path = images.relative_storage_path(media_id, video_format.extension)
            if self.options.dry_run:
                byte_size = path.stat().st_size
                if byte_size > self.settings.max_video_bytes:
                    self.report.warn("missing_media", reference, f"Video {video_id}: {videos.too_large_message(self.settings.max_video_bytes)}")
                    return None
            else:
                try:
                    byte_size = videos.store(stream, self.settings.media_root, storage_path, self.settings.max_video_bytes)
                except errors.ApiError as problem:
                    self.report.warn("missing_media", reference, f"Video {video_id}: {problem.message}")
                    return None
                self._written.append(self.settings.media_root / storage_path)
        media = Media(
            id=media_id,
            kind="video",
            storage_path=storage_path,
            content_type=video_format.content_type,
            byte_size=byte_size,
            width=None,
            height=None,
            alt="",
            original_filename=f"dozuki-video-{video_id}.{video_format.extension}",
            uploaded_by_id=actor.id,
        )
        self.db.add(media)
        self.db.flush()
        self.remember("video", video_id, media.id)
        return media

    # ------------------------------------------------------------ text

    def _absorb(self, reference: str, conversion: Conversion) -> str:
        for warning in conversion.warnings:
            self.report.warn(warning.code, reference, warning.message)
        return conversion.text

    def plain(self, reference: str, rendered: Any, raw: Any, limit: int, counter: list[int]) -> str:
        """A plain-text field, from the vendor's rendering if there is one.

        The rendered HTML is preferred over the wiki source because the vendor
        has already interpreted it, whatever syntax its editor of the day wrote;
        the wiki source is the fallback.
        """
        if _text(rendered).strip():
            conversion = html_to_plain(rendered, self.resolver)
        else:
            conversion = to_plain(_text(raw), self.resolver)
        counter[0] += conversion.links_flattened
        text, clipped = mapping.clip(self._absorb(reference, conversion), limit)
        if clipped:
            self.report.warn("clipped", reference, f"Text shortened to {limit} characters.")
        return text

    # ------------------------------------------------------------ guides

    def load_guides(self) -> None:
        entries = self._guide_index()
        if self.options.only_guides is not None:
            entries = [entry for entry in entries if entry["guideid"] in self.options.only_guides]
        self.log(f"Loading {len(entries)} guides…")
        for number, entry in enumerate(entries, start=1):
            guide_id = entry["guideid"]
            title = self.resolver.guides[guide_id].title
            with self.item("guide", f"{guide_id} “{title}”"):
                self.load_guide(guide_id, entry)
            if number % PROGRESS_EVERY == 0:
                self.log(f"  guide {number} of {len(entries)}")

    def _settled(self, kind: str, label: str, record: ImportRecord | None, existing: Any, mark: str) -> bool:
        """Whether the item needs no writing: unchanged, or edited in Reticle since."""
        if existing is None or record is None or self.options.force:
            return False
        if record.imported_updated_at is not None and existing.updated_at != record.imported_updated_at:
            self.report.add(
                kind, label, "skipped", "edited in Reticle since it was imported; left untouched (use --force to overwrite)"
            )
            return True
        if record.fingerprint == mark:
            self.report.add(kind, label, "unchanged")
            return True
        return False

    def load_guide(self, guide_id: int, entry: dict[str, Any]) -> None:
        payload = self.archive.read_json(Archive.guide(guide_id))
        if not isinstance(payload, dict):
            failure = self.archive.manifest_items().get(f"guide:{guide_id}", {}).get("error")
            raise LookupError(f"the guide is not in the archive ({failure or 'it was never exported'})")
        reference = f"guide {guide_id} “{self._guide_title(guide_id, payload)}”"
        tags = self.archive.read_json(Archive.guide_tags(guide_id))
        if not isinstance(tags, list):
            self.report.warn("tags", reference, "Its tags are not in the archive; imported without tags, so no guide list will show it.")
            tags = []

        used_images = sorted(
            {image["id"] for step in payload.get("steps") or [] if isinstance(step, dict) for image in self._step_media(step)[0]}
        )
        mark = fingerprint(
            MAPPING_VERSION, payload, tags, [self.archive.read_json(Archive.image_meta(image_id)) for image_id in used_images],
            [self.options.publish, self.options.markers, self.options.arrow_head, self.options.owner_email],
        )
        record = self.record("guide", guide_id)
        existing = self.db.get(Guide, record.reticle_id) if record is not None else None
        if self._settled("guide", reference.partition(" ")[2], record, existing, mark):
            return

        author_block = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        author = self.user_for(author_block.get("userid") or entry.get("userid"), _text(author_block.get("username")) or _text(entry.get("username")))
        flattened = [0]

        title, clipped = mapping.clip(self._guide_title(guide_id, payload), TITLE_LIMIT)
        if clipped:
            self.report.warn("clipped", reference, "Title shortened to 240 characters.")
        summary, clipped = mapping.clip(_text(payload.get("summary")).strip(), SUMMARY_LIMIT)
        if clipped:
            self.report.warn("clipped", reference, "Summary shortened to 4000 characters.")
        level, known = mapping.difficulty(payload.get("difficulty"))
        if not known and _text(payload.get("difficulty")).strip():
            self.report.warn("difficulty", reference, f"Difficulty {payload.get('difficulty')!r} is not a known value; set to “moderate”.")
        elif not known:
            self.report.note("Guides with no difficulty set on the old site were given “moderate”, Reticle's default.")
        low, high = mapping.time_range(payload.get("time_required_min"), payload.get("time_required_max"))

        category_title = _text(payload.get("category")).strip() or _text(entry.get("category")).strip()
        category_id = self.categories.get(category_title)
        if category_id is None:
            self.report.warn("category", reference, f"Its category “{category_title}” is not in the archive; filed under “{UNCATEGORISED}”.")
            category_id = self._uncategorised()

        steps = self._steps(reference, payload, author, flattened)

        if existing is None:
            guide = Guide(
                slug=self.guide_slugs[guide_id],
                title=title,
                category_id=category_id,
                author_id=author.id,
                last_edited_by_id=author.id,
            )
            content.add_contributor(self.db, GUIDES, guide, author)
            self.db.add(guide)
            self.db.flush()
        else:
            guide = existing

        document = GuideDocumentIn(
            title=title,
            summary=summary,
            category_id=category_id,
            tags=self._tags(reference, tags),
            difficulty=level,
            time_required_min_minutes=low,
            time_required_max_minutes=high,
            introduction=self.plain(reference, payload.get("introduction_rendered"), payload.get("introduction_raw"), PROSE_LIMIT, flattened),
            conclusion=self.plain(reference, payload.get("conclusion_rendered"), payload.get("conclusion_raw"), PROSE_LIMIT, flattened),
            steps=steps,
            expected_updated_at=guide.updated_at,
        )
        apply_guide_document(self.db, guide, document)
        self.db.flush()
        self.db.refresh(guide)

        if flattened[0]:
            self.report.warn(
                "links_flattened", reference, f"{flattened[0]} link(s) are now plain text: bullets and introductions are not clickable in Reticle."
            )
        flags = [
            _text(flag.get("flagid") if isinstance(flag, dict) else flag) for flag in payload.get("flags") or []
        ]
        if any(flags):
            self.report.warn("vendor_flag", reference, f"Flagged {', '.join(flag for flag in flags if flag)} on the old site; Reticle has no flags, so check its status.")

        public = bool(payload.get("public")) and not payload.get("isArchived") and not entry.get("isArchived")
        if not public:
            self.report.note("Guides that were private, unpublished or archived on the old site were imported as drafts.")
        self._finish(
            GUIDES, guide, author, reference, "guide", guide_id, mark,
            want_published=public and self.options.publish,
            was_public=public,
            created=mapping.instant(payload.get("created_date")),
            modified=mapping.instant(payload.get("modified_date")) or mapping.instant(entry.get("modified_date")),
            published=mapping.instant(payload.get("published_date")),
            outcome="created" if existing is None else "updated",
        )

    @staticmethod
    def _step_media(step: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
        """A step's images and videos; the third value names a media type that is neither."""
        media = step.get("media")
        if not isinstance(media, dict) or not media.get("data"):
            return [], [], None
        data = media["data"]
        entries = data if isinstance(data, list) else [data]
        pictures = [entry for entry in entries if is_image_object(entry)]
        clips = [entry for entry in entries if is_video_object(entry)]
        kind = str(media.get("type") or "")
        unknown = kind if not pictures and not clips and kind not in {"image", "video"} else None
        return pictures, clips, unknown

    def _steps(self, reference: str, payload: dict[str, Any], author: User, flattened: list[int]) -> list[StepIn]:
        cap = self.settings.max_media_per_step
        steps: list[StepIn] = []
        ordered = sorted(
            (step for step in payload.get("steps") or [] if isinstance(step, dict)),
            key=lambda step: step.get("orderby") if isinstance(step.get("orderby"), (int, float)) else 0,
        )
        for number, step in enumerate(ordered, start=1):
            where = f"{reference}, step {number}"
            title, clipped = mapping.clip(" ".join(_text(step.get("title")).split()), STEP_TITLE_LIMIT)
            if clipped:
                self.report.warn("clipped", where, "Step title shortened to 400 characters.")

            bullets: list[BulletIn] = []
            for line in step.get("lines") or []:
                if not isinstance(line, dict):
                    continue
                text = self.plain(where, line.get("text_rendered"), line.get("text_raw"), BULLET_LIMIT, flattened)
                if not text:
                    continue
                color, icon, known = mapping.bullet(line)
                if not known:
                    self.report.warn(
                        "unmapped_bullet", where, f"Bullet style {line.get('bullet')!r} is not a known value; shown as a {color} bullet."
                    )
                level, in_range = mapping.level(line.get("level"))
                if not in_range:
                    self.report.warn("level_clamped", where, f"Indent level {line.get('level')!r} was set to {level}.")
                bullets.append(BulletIn(text=text, color=color, icon=icon, level=level))
            if len(bullets) > MAX_BULLETS_PER_STEP:
                self.report.warn("clipped", where, f"{len(bullets) - MAX_BULLETS_PER_STEP} bullets beyond the first {MAX_BULLETS_PER_STEP} were left out.")
                bullets = bullets[:MAX_BULLETS_PER_STEP]

            pictures, clips, unknown = self._step_media(step)
            if unknown:
                self.report.warn("missing_media", where, f"Media of type “{unknown}” has no Reticle equivalent and was left out.")
            media: list[MediaRefIn] = []
            seen: set[str] = set()
            vendor_ids: set[int] = set()
            for picture in pictures:
                if picture["id"] in vendor_ids:
                    self.report.warn("duplicate_media", where, f"Image {picture['id']} appears twice in the step; it is shown once.")
                    continue
                vendor_ids.add(picture["id"])
                imported = self.step_image(where, picture["id"], author)
                if imported is not None and imported[0].id in seen:
                    imported = self.step_image(where, picture["id"], author, own_copy=True)
                if imported is None or imported[0].id in seen:
                    continue
                seen.add(imported[0].id)
                media.append(MediaRefIn(id=imported[0].id, annotations=[AnnotationIn(**annotation) for annotation in imported[1]]))
            for clip in clips:
                imported_video = self.video(where, clip["videoid"], author)
                if imported_video is not None and imported_video.id not in seen:
                    seen.add(imported_video.id)
                    media.append(MediaRefIn(id=imported_video.id))

            if not title and not bullets and not media:
                self.report.warn("empty_step", where, "The step had no title, no text and no importable media; it was left out.")
                continue

            steps.append(StepIn(title=title, bullets=bullets, media=media[:cap]))
            if len(media) > cap:
                extra = [media[index : index + cap] for index in range(cap, len(media), cap)]
                self.report.warn(
                    "split_step", where,
                    f"It held {len(media)} media items; Reticle allows {cap} per step, so {len(extra)} continuation step(s) follow it.",
                )
                for chunk in extra:
                    steps.append(StepIn(title=mapping.clip(f"{title or f'Step {number}'} (continued)", STEP_TITLE_LIMIT)[0], bullets=[], media=chunk))
        return steps

    def _tags(self, reference: str, tags: list[Any]) -> list[str]:
        kept: dict[str, str] = {}
        for tag in tags:
            name = " ".join(_text(tag).split())
            slug = tag_slug(name)
            if not slug:
                if name:
                    self.report.warn("tags", reference, f"Tag “{name}” has no letter or digit in it and was left out.")
                continue
            if len(name) > MAX_TAG_LENGTH:
                self.report.warn("tags", reference, f"Tag “{name[:40]}…” is longer than {MAX_TAG_LENGTH} characters and was left out.")
                continue
            self.tag_spellings.setdefault(slug, set()).add(name)
            kept.setdefault(slug, name)
        names = list(kept.values())
        if len(names) > MAX_TAGS_PER_GUIDE:
            self.report.warn("tags", reference, f"It has {len(names)} tags; only the first {MAX_TAGS_PER_GUIDE} were kept.")
            names = names[:MAX_TAGS_PER_GUIDE]
        return names

    # ------------------------------------------------------------ finishing

    def _finish(
        self,
        kind: content.ContentKind,
        entity: Any,
        actor: User,
        reference: str,
        record_kind: str,
        vendor_id: Any,
        mark: str,
        *,
        want_published: bool,
        was_public: bool,
        created: datetime | None,
        modified: datetime | None,
        published: datetime | None,
        outcome: str,
    ) -> None:
        """Status, timestamps, revision and bookkeeping for a guide or a page.

        Publishing is done with the application's own check and snapshot writer
        rather than ``content.publish``, for one reason: that function stamps
        the moment of the call, and an imported guide should keep the dates it
        was actually written and published on.
        """
        now = utcnow()
        if want_published:
            try:
                kind.assert_publishable(entity)
            except errors.ApiError as refusal:
                want_published = False
                self.report.warn("not_published", reference, f"Imported as a draft: {refusal.message}")
        elif was_public and not self.options.publish:
            self.report.note("Everything was imported as a draft (--as-drafts).")

        if outcome == "created":
            entity.created_at = created or modified or now
        entity.updated_at = modified or now
        entity.last_edited_by_id = actor.id
        if want_published:
            entity.status = PUBLISHED
            entity.version += 1
            entity.published_at = published or modified or now
            self.db.flush()
            content.write_revision(self.db, kind, entity, actor, entity.published_at)
        else:
            entity.status = "draft"
        self.db.flush()

        self.remember(record_kind, vendor_id, entity.id, mark, entity.updated_at)
        audit.record(
            self.db,
            action=f"{kind.name}.import",
            entity_type=kind.name,
            entity_id=entity.id,
            actor_id=actor.id,
            detail={"source": self.source, "vendorId": str(vendor_id), "outcome": outcome, "status": entity.status},
        )
        address = f"/{'g' if kind.name == 'guide' else 'w'}/{entity.slug}"
        self.report.add(kind.name, reference.partition(" ")[2], outcome, f"{entity.status}, {address}")

    # ------------------------------------------------------------ pages

    def load_pages(self) -> None:
        entries = self._wiki_index()
        self.log(f"Loading {len(entries)} pages…")
        for namespace, entry in entries:
            with self.item("page", f"{namespace} “{self._page_title(entry)}”"):
                self.load_page(namespace, entry)

        skipped = [namespace for namespace in self.manifest.get("namespaces") or [] if namespace not in self.options.namespaces]
        for namespace in skipped:
            listing = self.archive.read_json(Archive.wiki_index(namespace))
            if isinstance(listing, list) and listing:
                self.report.note(
                    f"{len(listing)} page(s) in the {namespace} namespace are in the archive but were not loaded. "
                    + (
                        "On a vendor site INFO holds the vendor's own boilerplate (FAQ, flag texts), which is not "
                        "your content; pass --namespaces to include it only if you wrote those pages yourselves."
                        if namespace == "INFO"
                        else "Pass --namespaces to include them."
                    )
                )

    def load_page(self, namespace: str, entry: dict[str, Any]) -> None:
        wiki_id = entry["wikiid"]
        payload = self.archive.read_json(Archive.wiki(namespace, wiki_id))
        if not isinstance(payload, dict):
            failure = self.archive.manifest_items().get(f"wiki:{namespace}:{wiki_id}", {}).get("error")
            raise LookupError(f"the page is not in the archive ({failure or 'it was never exported'})")
        title, clipped = mapping.clip(self._page_title({**entry, **{key: payload[key] for key in ("display_title", "title") if payload.get(key)}}), TITLE_LIMIT)
        reference = f"page {namespace} “{title}”"
        if clipped:
            self.report.warn("clipped", reference, "Title shortened to 240 characters.")

        mark = fingerprint(MAPPING_VERSION, payload, entry.get("modified_date"), [self.options.publish, self.options.owner_email])
        record = self.record("wiki", wiki_id)
        existing = self.db.get(Page, record.reticle_id) if record is not None else None
        if self._settled("page", reference.partition(" ")[2], record, existing, mark):
            return

        raw = _text(payload.get("contents_raw"))
        if not raw.strip():
            raise Skip("the page has no content")

        author_block = payload.get("author") if isinstance(payload.get("author"), dict) else {}
        author = self.user_for(author_block.get("userid"), _text(author_block.get("username")))

        for image_id in referenced_image_ids(raw):
            if image_id not in self.resolver.images:
                media = self.plain_image(reference, image_id, author)
                if media is not None:
                    self._remember(self.resolver.images, image_id, media.id)
        body = self._absorb(reference, to_markdown(raw, self.resolver))
        if len(body) > MAX_PAGE_BODY_CHARS:
            raise ValueError(f"the converted page is {len(body)} characters long; Reticle's limit is {MAX_PAGE_BODY_CHARS}")

        category_id = self.categories.get(str(entry["title"])) if namespace == "CATEGORY" else None
        is_landing = category_id is not None
        if is_landing:
            try:
                page_documents.assert_landing_slot_free(self.db, category_id, existing.id if existing is not None else None)
            except errors.ApiError:
                is_landing = False
                self.report.warn(
                    "landing", reference, "Its category already has a landing page in Reticle; imported as an ordinary page in that category."
                )
        elif namespace == "CATEGORY":
            self.report.note(
                f"The category page “{title}” has no matching category in Reticle (the site's root page is the usual "
                "case) and was imported as an ordinary page."
            )

        hero_id = None
        if is_image_object(payload.get("image")):
            hero = self.plain_image(reference, payload["image"]["id"], author)
            hero_id = hero.id if hero is not None else None

        summary, clipped = mapping.clip(
            self._absorb(reference, to_plain(_text(payload.get("description")) or _text(entry.get("summary")), self.resolver)), SUMMARY_LIMIT
        )
        if clipped:
            self.report.warn("clipped", reference, "Summary shortened to 4000 characters.")

        tags = self.archive.read_json(Archive.wiki_tags(namespace, wiki_id))
        if isinstance(tags, list) and tags:
            self.report.warn("page_tags", reference, f"Tags not carried over: {', '.join(str(tag) for tag in tags)}.")

        if existing is None:
            page = Page(
                slug=self.page_slugs[(namespace, wiki_id)],
                title=title,
                category_id=category_id,
                is_landing=is_landing,
                author_id=author.id,
                last_edited_by_id=author.id,
            )
            content.add_contributor(self.db, PAGES, page, author)
            self.db.add(page)
            self.db.flush()
        else:
            page = existing

        page_documents.apply_document(
            self.db,
            page,
            PageDocumentIn(
                title=title,
                summary=summary,
                category_id=category_id,
                is_landing=is_landing,
                body=body,
                hero_media_id=hero_id,
                expected_updated_at=page.updated_at,
            ),
        )
        self.db.flush()
        self.db.refresh(page)

        modified = mapping.instant(entry.get("modified_date"))
        self._finish(
            PAGES, page, author, reference, "wiki", wiki_id, mark,
            want_published=self.options.publish,
            was_public=True,
            created=modified,
            modified=modified,
            published=modified,
            outcome="created" if existing is None else "updated",
        )

    # ------------------------------------------------------------ closing

    def _closing_notes(self) -> None:
        for slug, spellings in sorted(self.tag_spellings.items()):
            if len(spellings) > 1:
                self.report.note(
                    f"Tag spellings {', '.join(sorted(spellings))} are one tag in Reticle (“{slug}”); "
                    "guide lists match them all, as they did on the old site if it ignored case."
                )
        hidden = [
            category.name
            for category in self.db.scalars(select(Category).where(Category.id.in_(list(self.categories.values())), Category.is_hidden.is_(True)).order_by(Category.name))
        ]
        if hidden:
            self.report.note("Holding categories marked hidden (kept out of the browsable tree): " + ", ".join(hidden) + ".")
        if self.options.markers == "burned":
            self.report.note("Image markers were left burned into the pictures (--markers burned); no annotations were created.")
        self.report.note(
            "Not available from the vendor API and therefore not imported: view counts, comments, revision history, "
            "original video uploads (only the vendor's transcode exists) and guide cover images (Reticle guides have none)."
        )


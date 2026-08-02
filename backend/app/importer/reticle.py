"""Reading a Reticle export back in.

This exists to make the export honest. A format nobody has restored is a
hypothesis, and the one time it gets tested for real is the day the server it
came from is gone — so the suite exports a corpus, imports it into an empty
database and compares the two documents field for field.

It is also the practical half of the promise. Moving an installation to another
machine, standing up a copy to try something on, and recovering from a mistake
are all the same operation: export, then this.

Identifiers are preserved rather than reminted. A guide's ULID appears in the
revision snapshots, in the provenance records and in whatever people have
bookmarked or cited, so a restore that renumbered everything would be a
different corpus that merely looked the same.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .. import images
from ..exporter import DOCUMENT_NAME, FORMAT_VERSION
from ..models import (
    Annotation,
    Bullet,
    Category,
    Guide,
    GuideContributor,
    GuideRevision,
    GuideTag,
    ImportedRecord,
    Media,
    Page,
    PageContributor,
    PageRevision,
    Step,
    StepMedia,
    Tag,
    User,
)
from ..security import hash_password
from ..settings import Settings
from ..slugs import slugify
from ..storage import build_storage
from .client import MigrationError


def safe_slug(value: object, fallback: str) -> str:
    """Put a slug out of an archive through the same rule the API applies.

    Everything else in a restore is written by this application and can be
    trusted to look like itself, but an archive is a file an administrator was
    handed, and its slugs go straight into URLs and — in ``static_site`` — into
    filenames. ``slug = "../../../../tmp/PWNED"`` in a hostile export would have
    the snapshot generator write outside the destination directory. ``slugify``
    emits only ``[a-z0-9-]``, so there is nothing left to traverse with.
    """
    return slugify(str(value or ""), fallback=fallback)


@dataclass
class RestoreReport:
    users: int = 0
    categories: int = 0
    tags: int = 0
    media: int = 0
    guides: int = 0
    pages: int = 0
    revisions: int = 0
    checksum_failures: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [
            "Reticle restore",
            "===============",
            "",
            f"  users       {self.users}",
            f"  categories  {self.categories}",
            f"  tags        {self.tags}",
            f"  media       {self.media}",
            f"  guides      {self.guides}",
            f"  pages       {self.pages}",
            f"  revisions   {self.revisions}",
            "",
        ]
        if self.missing_files:
            lines.append(f"Files named in the document but absent ({len(self.missing_files)}):")
            lines.extend(f"  {name}" for name in self.missing_files)
            lines.append("")
        if self.checksum_failures:
            lines.append(
                f"Files whose contents did not match their checksum ({len(self.checksum_failures)}):"
            )
            lines.extend(f"  {name}" for name in self.checksum_failures)
            lines.append("")
        if not self.missing_files and not self.checksum_failures:
            lines.append("Every file arrived intact.")
            lines.append("")
        return "\n".join(lines)

    @property
    def intact(self) -> bool:
        return not self.checksum_failures and not self.missing_files


def _instant(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)


def read_export(source: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Load an export from a directory or a ``.tar.gz``, whichever was handed over.

    Both forms are produced by the exporter and an operator should not have to
    remember which one they made.
    """
    if source.is_dir():
        document_path = source / DOCUMENT_NAME
        if not document_path.exists():
            raise MigrationError(f"{source} does not contain {DOCUMENT_NAME}.")
        document = json.loads(document_path.read_text(encoding="utf-8"))
        files: dict[str, bytes] = {}
        for entry in document.get("media", []):
            name = entry.get("file")
            if not name:
                continue
            path = source / name
            if path.exists():
                files[name] = path.read_bytes()
        return document, files

    if not source.exists():
        raise MigrationError(f"{source} does not exist.")

    document = None
    files = {}
    with tarfile.open(source, mode="r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:  # pragma: no cover - directories are filtered above
                continue
            payload = handle.read()
            if member.name.endswith(DOCUMENT_NAME):
                document = json.loads(payload.decode("utf-8"))
            else:
                files[member.name] = payload

    if document is None:
        raise MigrationError(f"{source} contains no {DOCUMENT_NAME}.")
    return document, files


def restore(
    db: DbSession,
    settings: Settings,
    document: dict[str, Any],
    files: dict[str, bytes],
    placeholder_password: str | None = None,
) -> RestoreReport:
    """Write a decoded export into an empty database.

    Refuses to run against one that already holds content. Merging two corpora
    is a different operation with different answers — which side wins a slug
    collision, what happens to two guides claiming one identifier — and doing it
    silently under the name "restore" is how somebody loses the half they meant
    to keep.
    """
    header = document.get("reticleExport") or {}
    version = header.get("formatVersion")
    if version != FORMAT_VERSION:
        raise MigrationError(
            f"That export is format version {version!r}; this Reticle reads version {FORMAT_VERSION}."
        )

    if db.scalar(select(Guide.id).limit(1)) or db.scalar(select(Page.id).limit(1)):
        raise MigrationError(
            "This database already holds guides or pages. Restore into an empty one."
        )

    report = RestoreReport()

    _restore_users(db, document, report, placeholder_password)
    _restore_categories(db, document, report)
    tags_by_slug = _restore_tags(db, document, report)
    _restore_media(db, settings, document, files, report)
    db.flush()

    for guide in document.get("guides", []):
        _restore_guide(db, guide, tags_by_slug)
        report.guides += 1
    for page in document.get("pages", []):
        _restore_page(db, page)
        report.pages += 1
    db.flush()

    for revision in document.get("guideRevisions", []):
        db.add(
            GuideRevision(
                guide_id=revision["guideId"],
                version=revision["version"],
                published_at=_instant(revision["publishedAt"]),
                published_by_id=revision["publishedById"],
                document=revision["document"],
            )
        )
        report.revisions += 1
    for revision in document.get("pageRevisions", []):
        db.add(
            PageRevision(
                page_id=revision["pageId"],
                version=revision["version"],
                published_at=_instant(revision["publishedAt"]),
                published_by_id=revision["publishedById"],
                document=revision["document"],
            )
        )
        report.revisions += 1

    for record in document.get("provenance", []):
        db.add(
            ImportedRecord(
                source_system=record["sourceSystem"],
                source_kind=record["sourceKind"],
                source_id=record["sourceId"],
                source_url=record.get("sourceUrl", ""),
                local_id=record["localId"],
            )
        )

    db.commit()
    return report


def _restore_users(
    db: DbSession, document: dict[str, Any], report: RestoreReport, placeholder: str | None
) -> None:
    """Recreate the accounts, which arrive without credentials by design.

    Each one gets an unusable password unless the operator supplies a
    placeholder, because an account that cannot be signed into is a safe
    default and an account with a known password is not. Everyone signs in
    again after a restore; the alternative is a corpus attributed to nobody.
    """
    secret = placeholder or "restore-placeholder-" + hashlib.sha256(b"reticle").hexdigest()[:24]
    for entry in document.get("users", []):
        db.add(
            User(
                id=entry["id"],
                email=entry["email"],
                display_name=entry["displayName"],
                role=entry["role"],
                is_active=entry["isActive"],
                password_hash=hash_password(secret),
                created_at=_instant(entry["createdAt"]),
            )
        )
        report.users += 1


def _restore_categories(db: DbSession, document: dict[str, Any], report: RestoreReport) -> None:
    """Parents are attached in a second pass.

    A category can name one that appears later in the file, and an insert that
    assumed otherwise would fail on whichever ordering the source happened to
    produce.
    """
    entries = document.get("categories", [])
    for entry in entries:
        db.add(
            Category(
                id=entry["id"],
                slug=safe_slug(entry["slug"], "category"),
                name=entry["name"],
                description=entry["description"],
                parent_id=None,
                order_index=entry["orderIndex"],
                is_hidden=entry["isHidden"],
            )
        )
        report.categories += 1
    db.flush()

    for entry in entries:
        if entry.get("parentId"):
            category = db.get(Category, entry["id"])
            if category is not None:
                category.parent_id = entry["parentId"]


def _restore_tags(db: DbSession, document: dict[str, Any], report: RestoreReport) -> dict[str, Tag]:
    tags: dict[str, Tag] = {}
    for entry in document.get("tags", []):
        tag = Tag(id=entry["id"], slug=safe_slug(entry["slug"], "tag"), name=entry["name"])
        db.add(tag)
        tags[tag.slug] = tag
        report.tags += 1
    db.flush()
    return tags


def _restore_media(
    db: DbSession,
    settings: Settings,
    document: dict[str, Any],
    files: dict[str, bytes],
    report: RestoreReport,
) -> None:
    """Write the files back out, checking each against its recorded checksum.

    The check is the point of carrying one. A transfer that silently truncated
    a photograph would otherwise be discovered by whoever opens that guide, and
    by then the source is gone.
    """
    for entry in document.get("media", []):
        name = entry.get("file")
        payload = files.get(name) if name else None

        if name and payload is None:
            report.missing_files.append(name)
        elif payload is not None and entry.get("sha256"):
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                report.checksum_failures.append(name)

        storage_path = ""
        if payload is not None and name:
            extension = Path(name).suffix.lstrip(".")
            storage_path = images.relative_storage_path(entry["id"], extension)
            build_storage(settings).write(storage_path, payload)

        db.add(
            Media(
                id=entry["id"],
                storage_path=storage_path or f"restored/{entry['id']}",
                content_type=entry.get("contentType", "application/octet-stream"),
                kind=entry.get("kind", "image"),
                byte_size=entry.get("byteSize", len(payload or b"")),
                width=entry.get("width"),
                height=entry.get("height"),
                duration_seconds=entry.get("durationSeconds"),
                alt=entry.get("alt", ""),
                original_filename=entry.get("originalFilename", ""),
                uploaded_by_id=entry["uploadedById"],
                created_at=_instant(entry.get("createdAt")),
            )
        )
        report.media += 1


def _restore_guide(db: DbSession, entry: dict[str, Any], tags_by_slug: dict[str, Tag]) -> None:
    guide = Guide(
        id=entry["id"],
        slug=safe_slug(entry["slug"], "guide"),
        title=entry["title"],
        summary=entry["summary"],
        category_id=entry["categoryId"],
        difficulty=entry["difficulty"],
        time_required_min_minutes=entry["timeRequiredMinMinutes"],
        time_required_max_minutes=entry["timeRequiredMaxMinutes"],
        introduction=entry["introduction"],
        conclusion=entry["conclusion"],
        status=entry["status"],
        # Read with a default, unlike its neighbours, because an archive written
        # by a Reticle from before quick links exists carries the same format
        # version and simply has no such key.
        is_quick_link=entry.get("isQuickLink", False),
        version=entry["version"],
        view_count=entry["viewCount"],
        author_id=entry["author"]["id"],
        last_edited_by_id=entry["lastEditedBy"]["id"],
        created_at=_instant(entry["createdAt"]),
        updated_at=_instant(entry["updatedAt"]),
        published_at=_instant(entry["publishedAt"]),
    )
    db.add(guide)
    db.flush()

    for index, slug in enumerate(entry.get("tags", [])):
        tag = tags_by_slug.get(safe_slug(slug, "tag"))
        if tag is not None:
            db.add(GuideTag(guide_id=guide.id, tag_id=tag.id, order_index=index))

    for person in entry.get("contributors", []):
        db.add(GuideContributor(guide_id=guide.id, user_id=person["id"]))

    for position, step_entry in enumerate(entry.get("steps", [])):
        step = Step(
            id=step_entry["id"],
            guide_id=guide.id,
            order_index=position,
            # `.get` because an archive written before blocks had a kind carries
            # the same format version and simply has no such key; everything in
            # one of those is a numbered step.
            kind=step_entry.get("kind", "step"),
            title=step_entry["title"],
            video_media_id=(step_entry.get("video") or {}).get("id"),
        )
        db.add(step)
        db.flush()

        for bullet_index, bullet in enumerate(step_entry.get("bullets", [])):
            db.add(
                Bullet(
                    id=bullet["id"],
                    step_id=step.id,
                    order_index=bullet_index,
                    text=bullet["text"],
                    color=bullet["color"],
                    icon=bullet["icon"],
                    level=bullet["level"],
                )
            )

        for media_index, item in enumerate(step_entry.get("media", [])):
            db.add(StepMedia(step_id=step.id, media_id=item["id"], order_index=media_index))
            _restore_annotations(db, item)

        if step_entry.get("video"):
            _restore_annotations(db, step_entry["video"])


def _restore_annotations(db: DbSession, item: dict[str, Any]) -> None:
    """Shapes belong to the file, so they are written once per media entry.

    Guarded against a second write because one image can appear on more than
    one step, and duplicating its shapes would draw every rectangle twice.
    """
    existing = db.scalar(select(Annotation.id).where(Annotation.media_id == item["id"]).limit(1))
    if existing:
        return
    for index, shape in enumerate(item.get("annotations", [])):
        db.add(
            Annotation(
                id=shape["id"],
                media_id=item["id"],
                order_index=index,
                shape=shape["shape"],
                color=shape["color"],
                x=shape["x"],
                y=shape["y"],
                width=shape["width"],
                height=shape["height"],
            )
        )


def _restore_page(db: DbSession, entry: dict[str, Any]) -> None:
    page = Page(
        id=entry["id"],
        slug=safe_slug(entry["slug"], "page"),
        title=entry["title"],
        summary=entry["summary"],
        category_id=entry["categoryId"],
        is_landing=entry["isLanding"],
        body=entry["body"],
        hero_media_id=entry["heroMediaId"],
        status=entry["status"],
        version=entry["version"],
        view_count=entry["viewCount"],
        author_id=entry["author"]["id"],
        last_edited_by_id=entry["lastEditedBy"]["id"],
        created_at=_instant(entry["createdAt"]),
        updated_at=_instant(entry["updatedAt"]),
        published_at=_instant(entry["publishedAt"]),
    )
    db.add(page)
    db.flush()

    for person in entry.get("contributors", []):
        db.add(PageContributor(page_id=page.id, user_id=person["id"]))

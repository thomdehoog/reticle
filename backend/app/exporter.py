"""Getting everything out again.

ZMB is replacing a hosted platform whose data could only be retrieved through
an API that disappears with the subscription. Building a second system with the
same property would be repeating the mistake at our own expense, so the way out
is part of the product rather than a favour somebody performs later with a
database client.

Three properties make an export worth having, and all three are deliberate.

**It is readable without this software.** The document is JSON with documented
field names — the same camelCase shapes the HTTP API already serves — not a
SQLite file that only SQLAlchemy models can interpret. Somebody writing an
importer for a different platform needs ``docs/EXPORT.md`` and nothing else.

**It contains the files, not links to them.** A manifest of URLs is worthless
the day the server is switched off, which is precisely the day an export gets
used. The archive carries every image and video, with a SHA-256 for each so a
transfer can be proved intact.

**It round-trips.** ``app.importer.reticle`` reads this format back, and the
test suite exports a corpus, imports it into an empty database and compares the
two documents field for field. An export nobody has restored is a hypothesis.

Secrets never appear. Password hashes, session tokens and the login-throttle
ledger are all excluded: this file will be copied onto a laptop and emailed to
whoever is doing the migration, and it should be worth nothing to whoever else
ends up with it.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from .models import (
    Category,
    Guide,
    GuideRevision,
    ImportedRecord,
    Media,
    Page,
    PageRevision,
    Tag,
    User,
)
from .schemas import (
    category_out,
    guide_document,
    iso_utc,
    media_out,
    page_document,
    user_out,
)
from .settings import Settings
from .storage import build_storage

FORMAT_VERSION = 1
"""The export format's own version.

Separate from the application's. A reader that understands version 1 must be
able to say so, and a later Reticle that changes the shape has to change this
number rather than quietly emitting something different under the same name.
"""

DOCUMENT_NAME = "reticle-export.json"
MEDIA_DIRECTORY = "media"


def media_entry(media: Media, settings: Settings) -> dict[str, Any]:
    """One file's metadata, including where it sits in the archive.

    The checksum is computed from the bytes on disk rather than recorded at
    upload, so it describes the file that is actually being handed over — a
    corrupted media store shows up here rather than three years later.
    """
    entry = media_out(media).model_dump(mode="json", by_alias=True)
    # Through the storage interface rather than the filesystem, so an export
    # keeps working when the files live in a bucket. The extension comes from
    # the stored path rather than from a real file for the same reason.
    payload = build_storage(settings).read(media.storage_path)
    extension = media.storage_path.rpartition(".")[2]

    entry.update(
        {
            "contentType": media.content_type,
            "byteSize": media.byte_size,
            "originalFilename": media.original_filename,
            "uploadedById": media.uploaded_by_id,
            "createdAt": iso_utc(media.created_at),
            "file": f"{MEDIA_DIRECTORY}/{media.id}.{extension}" if extension else None,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    )
    return entry


def build_document(db: DbSession, settings: Settings) -> dict[str, Any]:
    """The whole corpus as one self-describing object.

    Guides and pages are emitted in exactly the shape ``GET /api/guides/{id}``
    and ``GET /api/pages/{id}`` return, so the export needs no second contract
    and cannot drift from the one that is already documented and tested.
    """
    users = db.scalars(select(User).order_by(User.created_at, User.id)).all()
    categories = db.scalars(select(Category).order_by(Category.order_index, Category.id)).all()
    tags = db.scalars(select(Tag).order_by(Tag.slug)).all()
    media = db.scalars(select(Media).order_by(Media.created_at, Media.id)).all()
    guides = db.scalars(select(Guide).order_by(Guide.created_at, Guide.id)).all()
    pages = db.scalars(select(Page).order_by(Page.created_at, Page.id)).all()

    guide_documents = [guide_document(guide) for guide in guides]
    page_documents = [page_document(page) for page in pages]

    guide_revisions = [
        {
            "guideId": revision.guide_id,
            "version": revision.version,
            "publishedAt": iso_utc(revision.published_at),
            "publishedById": revision.published_by_id,
            "document": revision.document,
        }
        for revision in db.scalars(
            select(GuideRevision).order_by(GuideRevision.guide_id, GuideRevision.version)
        ).all()
    ]
    page_revisions = [
        {
            "pageId": revision.page_id,
            "version": revision.version,
            "publishedAt": iso_utc(revision.published_at),
            "publishedById": revision.published_by_id,
            "document": revision.document,
        }
        for revision in db.scalars(
            select(PageRevision).order_by(PageRevision.page_id, PageRevision.version)
        ).all()
    ]

    # Where a migrated document came from, carried forward so the thread back to
    # the original survives a second move rather than ending at this system.
    provenance = [
        {
            "sourceSystem": record.source_system,
            "sourceKind": record.source_kind,
            "sourceId": record.source_id,
            "sourceUrl": record.source_url,
            "localId": record.local_id,
        }
        for record in db.scalars(
            select(ImportedRecord).order_by(ImportedRecord.source_kind, ImportedRecord.source_id)
        ).all()
    ]

    media_entries = [media_entry(item, settings) for item in media]

    return {
        "reticleExport": {
            "formatVersion": FORMAT_VERSION,
            "exportedAt": iso_utc(datetime.now(UTC)),
            "application": "Reticle",
            "documentation": "docs/EXPORT.md",
            "counts": {
                "users": len(users),
                "categories": len(categories),
                "tags": len(tags),
                "media": len(media_entries),
                "guides": len(guide_documents),
                "pages": len(page_documents),
                "guideRevisions": len(guide_revisions),
                "pageRevisions": len(page_revisions),
            },
        },
        # Accounts, without anything that authenticates one. A destination system
        # needs to know who wrote what; it must never receive a credential.
        "users": [user_out(user).model_dump(mode="json", by_alias=True) for user in users],
        "categories": [
            category_out(category).model_dump(mode="json", by_alias=True) for category in categories
        ],
        "tags": [{"id": tag.id, "slug": tag.slug, "name": tag.name} for tag in tags],
        "media": media_entries,
        "guides": guide_documents,
        "pages": page_documents,
        "guideRevisions": guide_revisions,
        "pageRevisions": page_revisions,
        "provenance": provenance,
    }


def stream_archive(db: DbSession, settings: Settings) -> Iterator[bytes]:
    """The document and every file it references, as a gzipped tar.

    Streamed rather than assembled. ZMB's corpus is a few hundred guides and
    several gigabytes of microscopy images, and building that in memory to hand
    somebody a download would take the server out — on the one day they most
    need it to work.
    """
    document = build_document(db, settings)
    payload = json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")

    buffer = _StreamBuffer()
    with tarfile.open(fileobj=buffer, mode="w|gz") as archive:
        info = tarfile.TarInfo(DOCUMENT_NAME)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        yield buffer.take()

        for entry in document["media"]:
            if not entry.get("file"):
                continue
            media = db.get(Media, entry["id"])
            if media is None:  # pragma: no cover - the document was just built from these
                continue
            _add_to_archive(archive, build_storage(settings), media, entry["file"])
            chunk = buffer.take()
            if chunk:
                yield chunk

    remainder = buffer.take()
    if remainder:
        yield remainder


def _add_to_archive(archive: tarfile.TarFile, store, media: Media, arcname: str) -> None:
    """Add one file, preferring a path over bytes when the backend has one.

    The distinction is not cosmetic. ``TarFile.add`` streams from disk, so a
    local export never holds a file in memory; the remote branch has to read
    the object first, and on a corpus of several gigabytes that difference is
    the whole reason the export is streamed at all. Local installations — which
    is every installation today — keep the streaming path.
    """
    path = store.local_path(media.storage_path)
    if path is not None:
        archive.add(path, arcname=arcname)
        return

    payload = store.read(media.storage_path)
    info = tarfile.TarInfo(arcname)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


class _StreamBuffer(io.RawIOBase):
    """A file-like that hands each written chunk straight to the caller.

    ``tarfile`` writes to a file object; a streaming response reads from an
    iterator. This is the join between them, and it exists so that neither the
    archive nor the media it contains is ever held in memory in full.
    """

    def __init__(self) -> None:
        self._pending = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:  # type: ignore[override]
        self._pending.extend(data)
        return len(data)

    def take(self) -> bytes:
        chunk = bytes(self._pending)
        self._pending.clear()
        return chunk


def write_to_directory(db: DbSession, settings: Settings, destination: Path) -> dict[str, Any]:
    """Write the export as a plain directory.

    The form an operator actually wants for a scheduled backup or for handing a
    folder to whoever is doing the migration: no archive to unpack, and the
    media are ordinary files that any tool can read.
    """
    destination.mkdir(parents=True, exist_ok=True)
    media_root = destination / MEDIA_DIRECTORY
    media_root.mkdir(exist_ok=True)

    document = build_document(db, settings)
    (destination / DOCUMENT_NAME).write_text(
        json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    for entry in document["media"]:
        if not entry.get("file"):
            continue
        media = db.get(Media, entry["id"])
        if media is None:  # pragma: no cover
            continue
        (destination / entry["file"]).write_bytes(build_storage(settings).read(media.storage_path))

    return document

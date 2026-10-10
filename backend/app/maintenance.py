"""Housekeeping an operator runs by hand or from a timer.

One command::

    python -m app.maintenance purge-orphans [--older-than-days N] [--dry-run]

It deletes what Reticle keeps and nothing uses any more:

* **uploads that nothing shows** — in no guide step, no page body, no page hero
  and no published snapshot, past or present — and that are older than ``N``
  days (7 unless told otherwise), with their files;
* **files in the media directory that no upload row owns**, older than the same
  ``N`` days: what an interrupted upload or a restored database leaves behind;
* **expired sessions and login-attempt rows**, which the server also trims on
  start-up and as people sign in;
* **cached PDF exports** of anything that is no longer the published version;
* **index rows for content that is no longer published**, which only a writer
  that bypassed the application can leave.

It is safe to run while the server is up and safe to run twice. ``--dry-run``
reports what would go and changes nothing. Nothing here touches content: a
guide, a page, a published version and everything any of them shows is exactly
what this command is built not to delete. To remove one specific upload that
*is* in use, use ``DELETE /api/media/{id}?force=true`` as an administrator.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from . import audit, db, migrate, published, security, uploads
from .db import utcnow
from .models import PUBLISHED, Guide, Media, PublishedGuide, is_valid_id
from .settings import Settings, get_settings

DEFAULT_OLDER_THAN_DAYS = 7


@dataclass
class PurgeReport:
    """What one run removed, or would have."""

    dry_run: bool
    media: list[str] = field(default_factory=list)
    media_bytes: int = 0
    stray_files: list[Path] = field(default_factory=list)
    login_attempts: int = 0
    sessions: int = 0
    cached_exports: list[Path] = field(default_factory=list)
    stale_index_rows: int = 0

    def lines(self) -> list[str]:
        verb = "Would remove" if self.dry_run else "Removed"
        megabytes = self.media_bytes / (1024 * 1024)
        return [
            f"{verb} {len(self.media)} unused upload(s), {megabytes:.1f} MB.",
            f"{verb} {len(self.stray_files)} file(s) in the media directory that no upload owns.",
            f"{verb} {self.sessions} expired session(s) and {self.login_attempts} old login attempt(s).",
            f"{verb} {len(self.cached_exports)} cached PDF export(s) that are no longer current.",
            f"{verb} {self.stale_index_rows} index row(s) for content that is no longer published.",
        ]


def _is_older(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def stray_files(media_root: Path, known_ids: set[str], cutoff: float) -> list[Path]:
    """Files under the upload directories whose name is not a stored upload's.

    Only the two-level directories uploads are sharded into are looked at, and
    only files named after an identifier: anything else in the media root —
    the PDF cache, something an operator put there — is not this command's to
    judge. The age test is on the file, so a file being written right now for
    an upload whose row is about to be committed is left alone.
    """
    if not media_root.is_dir():
        return []
    found: list[Path] = []
    for outer in sorted(media_root.iterdir()):
        if not outer.is_dir() or len(outer.name) != 2:
            continue
        for inner in sorted(outer.iterdir()):
            if not inner.is_dir() or len(inner.name) != 2:
                continue
            for path in sorted(inner.iterdir()):
                owner = path.name.lstrip(".").split(".")[0]
                if path.is_file() and is_valid_id(owner) and owner not in known_ids and _is_older(path, cutoff):
                    found.append(path)
    return found


def stale_exports(session: DbSession, settings: Settings) -> list[Path]:
    """Cached PDFs that no request will ask for again.

    A cached export is named after the snapshot it was rendered from. It is
    current only while that snapshot is the one readers are served.
    """
    root = settings.pdf_cache_root
    if not root.is_dir():
        return []
    current = dict(
        session.execute(
            select(PublishedGuide.owner_id, PublishedGuide.revision_id)
            .join(Guide, Guide.id == PublishedGuide.owner_id)
            .where(Guide.status == PUBLISHED)
        ).all()
    )
    stale: list[Path] = []
    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        revision_id = current.get(directory.name)
        for path in sorted(directory.iterdir()):
            if path.is_file() and (revision_id is None or not path.name.startswith(f"{revision_id}-")):
                stale.append(path)
    return stale


def purge_orphans(session: DbSession, settings: Settings, older_than_days: int, dry_run: bool) -> PurgeReport:
    report = PurgeReport(dry_run=dry_run)
    cutoff = utcnow() - timedelta(days=older_than_days)

    known_ids = set(session.scalars(select(Media.id)))
    unused = uploads.unused_media(session, cutoff)
    report.media = [media.id for media in unused]
    report.media_bytes = sum(media.byte_size for media in unused)
    doomed_paths = [media.storage_path for media in unused]
    for media in unused:
        session.delete(media)
    if unused:
        audit.record(
            session,
            action="media.purge",
            entity_type="media",
            detail={"count": len(unused), "bytes": report.media_bytes, "olderThanDays": older_than_days},
        )

    report.login_attempts, report.sessions = security.prune_stale_rows(session)
    report.stale_index_rows = published.withdraw_stale(session)

    # Files of the uploads removed above are deleted with them, below; "stray"
    # is what belonged to no row even before this run.
    report.stray_files = stray_files(settings.media_root, known_ids, time.time() - older_than_days * 86400)
    report.cached_exports = stale_exports(session, settings)

    if dry_run:
        session.rollback()
        return report

    # Rows first, files after: a file without a row is swept up by the next
    # run, a row without a file is a broken picture.
    session.commit()
    for storage_path in doomed_paths:
        uploads.remove_files(settings.media_root, storage_path)
    for path in [*report.stray_files, *report.cached_exports]:
        path.unlink(missing_ok=True)
    for directory in sorted(settings.pdf_cache_root.iterdir()) if settings.pdf_cache_root.is_dir() else []:
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.maintenance", description="Reticle housekeeping.")
    commands = parser.add_subparsers(dest="command", required=True)
    purge = commands.add_parser(
        "purge-orphans",
        help="delete uploads nothing uses, stray files, expired sessions and stale PDF exports",
    )
    purge.add_argument(
        "--older-than-days",
        type=int,
        default=DEFAULT_OLDER_THAN_DAYS,
        metavar="N",
        help=f"only remove uploads and files at least N days old (default {DEFAULT_OLDER_THAN_DAYS})",
    )
    purge.add_argument("--dry-run", action="store_true", help="report what would be removed and change nothing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if arguments.older_than_days < 0:
        print("reticle: --older-than-days must not be negative.", file=sys.stderr)
        return 2
    try:
        migrate.assert_current(db.engine)
    except migrate.SchemaError as problem:
        print(f"reticle: {problem}", file=sys.stderr)
        return 1

    with db.SessionLocal() as session:
        report = purge_orphans(session, get_settings(), arguments.older_than_days, arguments.dry_run)
    print("\n".join(report.lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Snapshot, archive and verify Reticle's data for backups and upgrades.

Runs inside the application container, where the database is. A live SQLite
database in WAL mode is three files that are only consistent together and only
at certain instants, so copying ``reticle.db`` while the server runs can produce
a file that opens today and fails next month. SQLite's online-backup API takes
the copy through the database engine instead: it sees a single committed state
and the server keeps serving while it runs.

    dbtool.py snapshot <destination>        consistent copy of the live database
    dbtool.py check <file>                  is this a usable Reticle database?
    dbtool.py manifest <file>               a few facts about it, for the archive
    dbtool.py archive <snapshot> <media>    the backup archive (tar) on stdout
    dbtool.py schema-state                  would this release migrate the database?
    dbtool.py backup-confirm                note that a backup was stored just now
    dbtool.py backup-is-fresh               exit 0 if such a note is recent enough

Standard library only, on purpose: a backup tool should not depend on the
application importing cleanly. The one exception is ``schema-state``, which
asks Alembic (not the application) which revision this release's migrations
end at.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import io
import os
import sqlite3
import stat
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = "sqlite:////data/reticle.db"

# ===========================================================================
# WHAT A BACKUP TAKES FROM THE MEDIA ROOT — the one place that decides it.
#
# Rule: every regular file under the media root, except
#
#   1. anything inside a directory with one of these names, or inside any
#      directory whose name starts with a dot, at any depth. These hold work
#      in progress and caches (the rendered-PDF cache is `.pdf-cache`):
#      nothing in them is needed to restore the site, and a cache can be
#      several times the size of what it caches. Uploads themselves live in
#      directories named after the first characters of their identifier,
#      which are never one of these. (The upload spool, /data/tmp, is outside
#      the media root and is never looked at in the first place.)
MEDIA_EXCLUDED_DIRECTORIES = frozenset({"tmp", "cache", ".tmp", ".cache", ".pdf-cache"})
MEDIA_EXCLUDE_HIDDEN = True
#
#   2. files that are by their name unfinished or scratch: these suffixes,
#      and (with MEDIA_EXCLUDE_HIDDEN) any file whose name starts with a dot —
#      which is how the application names a file it is still writing;
MEDIA_EXCLUDED_SUFFIXES = (".tmp", ".part", ".partial")
#
#   3. files whose name contains one of these. Empty by default. A display
#      copy sits beside its original as <id>.display.<ext> and is made again
#      on demand if it is missing; adding ".display." here leaves them out,
#      for smaller archives at the price of a slower first view of each large
#      image after a restore;
MEDIA_EXCLUDED_NAME_PARTS: tuple[str, ...] = ()
#
#   4. files the database snapshot does not know AND that changed within the
#      last few minutes. A video is written straight to its final name and
#      its database row is committed only when the last byte is on disk; so a
#      file like that is an upload still in flight (or one that finished after
#      the snapshot was taken — the snapshot does not refer to it either way).
#      Copying it would archive half a video, and reading it while it grows
#      is what used to make the nightly backup fail whenever somebody was
#      uploading at 02:30.
MEDIA_SETTLE_SECONDS = 300
#
# Files the snapshot does not know but that have been lying still for longer
# are taken: display copies, and uploads nothing refers to yet. Files the
# snapshot DOES know (table `media`, column `storage_path`) are always taken,
# whatever their name or age — rules 2 to 4 never apply to them.
# ===========================================================================

# Where `backup-confirm` leaves its note, and how old the note may be for a
# pending migration to go ahead without RETICLE_ALLOW_MIGRATE=1.
BACKUP_NOTE_NAME = ".last-backup"
BACKUP_FRESH_MINUTES_DEFAULT = 60

COPY_CHUNK_BYTES = 1024 * 1024


def warn(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def live_database() -> Path:
    url = os.environ.get("RETICLE_DATABASE_URL", DEFAULT_URL)
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        sys.exit(
            "This backup tool only knows SQLite, and RETICLE_DATABASE_URL points elsewhere. "
            "Back a PostgreSQL database up with pg_dump."
        )
    return Path(url[len(prefix):])


def verify(path: Path) -> str:
    """Return the schema revision, or exit explaining why the file is unusable."""
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            verdict = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if verdict != "ok":
                sys.exit(f"{path}: SQLite integrity check failed: {verdict}")
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as error:
        sys.exit(f"{path}: not a usable Reticle database ({error}).")
    if row is None:
        sys.exit(f"{path}: the database has no schema revision recorded.")
    return row[0]


def snapshot(destination: Path) -> None:
    source_path = live_database()
    if not source_path.exists():
        sys.exit(f"There is no database at {source_path} to back up.")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    revision = verify(destination)
    size = destination.stat().st_size
    print(f"database snapshot: {size} bytes, schema revision {revision}, integrity ok")


def manifest_lines(path: Path) -> list[str]:
    revision = verify(path)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        counts = {}
        for table in ("users", "guides", "pages", "media"):
            try:
                counts[table] = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = "?"
    finally:
        connection.close()
    lines = [
        "Reticle backup",
        f"created: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"schema-revision: {revision}",
        f"image-version: {os.environ.get('RETICLE_IMAGE_VERSION', 'unknown')}",
    ]
    lines.extend(f"{table}: {count}" for table, count in counts.items())
    return lines


# ---------------------------------------------------------------------------
# The archive


def referenced_media(snapshot_path: Path) -> set[str]:
    """Every ``storage_path`` the snapshot knows, relative to the media root."""
    connection = sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True)
    try:
        return {row[0] for row in connection.execute("SELECT storage_path FROM media") if row[0]}
    except sqlite3.Error as error:
        sys.exit(f"{snapshot_path}: cannot read the media table ({error}).")
    finally:
        connection.close()


class MediaSelection:
    def __init__(self) -> None:
        self.files: list[str] = []
        self.in_flight: list[str] = []
        self.excluded = 0
        self.missing: list[str] = []


def _excluded_directory(name: str) -> bool:
    return name in MEDIA_EXCLUDED_DIRECTORIES or (MEDIA_EXCLUDE_HIDDEN and name.startswith("."))


def _excluded_file(name: str) -> bool:
    return (
        name.endswith(MEDIA_EXCLUDED_SUFFIXES)
        or (MEDIA_EXCLUDE_HIDDEN and name.startswith("."))
        or any(part in name for part in MEDIA_EXCLUDED_NAME_PARTS)
    )


def select_media(media_root: Path, referenced: set[str], now: float) -> MediaSelection:
    """Apply the rules at the top of this file to what is on disk right now."""
    selection = MediaSelection()
    seen: set[str] = set()
    if media_root.is_dir():
        for directory, subdirectories, names in os.walk(media_root):
            kept = [name for name in subdirectories if not _excluded_directory(name)]
            selection.excluded += len(subdirectories) - len(kept)
            subdirectories[:] = sorted(kept)
            for name in sorted(names):
                full = Path(directory) / name
                relative = full.relative_to(media_root).as_posix()
                try:
                    status = full.lstat()
                except FileNotFoundError:
                    continue  # deleted while we were looking; not ours to keep
                if not stat.S_ISREG(status.st_mode):
                    selection.excluded += 1  # a symlink or a socket is not an upload
                    continue
                if relative in referenced:
                    selection.files.append(relative)
                    seen.add(relative)
                elif _excluded_file(name):
                    selection.excluded += 1
                elif now - status.st_mtime < MEDIA_SETTLE_SECONDS:
                    selection.in_flight.append(relative)
                else:
                    selection.files.append(relative)
    selection.missing = sorted(referenced - seen)
    return selection


def _directory_entry(name: str, mtime: float) -> tarfile.TarInfo:
    entry = tarfile.TarInfo(name)
    entry.type = tarfile.DIRTYPE
    entry.mode = 0o700
    entry.mtime = int(mtime)
    entry.uid = os.getuid()
    entry.gid = os.getgid()
    return entry


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes, mtime: float) -> None:
    entry = tarfile.TarInfo(name)
    entry.size = len(payload)
    entry.mode = 0o600
    entry.mtime = int(mtime)
    entry.uid = os.getuid()
    entry.gid = os.getgid()
    archive.addfile(entry, io.BytesIO(payload))


class _ExactLength:
    """Hand tarfile exactly ``size`` bytes of a file, whatever happens to it.

    The header already promised that many. A file that has grown since is cut
    at the size it had; one that has shrunk is padded with zeros and reported,
    because a short member would shift every later one and ruin the archive.
    """

    def __init__(self, handle: io.BufferedReader, size: int) -> None:
        self.handle = handle
        self.remaining = size
        self.padded = 0

    def read(self, count: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        wanted = self.remaining if count is None or count < 0 else min(count, self.remaining)
        chunk = self.handle.read(wanted)
        if len(chunk) < wanted:
            self.padded += wanted - len(chunk)
            chunk += b"\0" * (wanted - len(chunk))
        self.remaining -= len(chunk)
        return chunk


def archive(snapshot_path: Path, media_root: Path) -> None:
    """Write MANIFEST, reticle.db and the selected media as one tar to stdout.

    Written here rather than by tar(1) because tar treats "this file changed
    while I was reading it" and "this file vanished" as failures of the whole
    run, and on a site where people upload and delete while the backup runs
    both are ordinary. What counts as a failure here is narrower and stated
    below: a file the database snapshot refers to that cannot be read whole.
    """
    started = time.time()
    referenced = referenced_media(snapshot_path)
    selection = select_media(media_root, referenced, started)
    lines = manifest_lines(snapshot_path)
    lines.append(f"media-files: {len(selection.files)}")
    lines.append(f"media-skipped-in-flight: {len(selection.in_flight)}")
    lines.append(f"media-missing: {len(selection.missing)}")

    failures: list[str] = []
    vanished: list[str] = []
    output = sys.stdout.buffer
    # GNU format: plain headers that GNU tar, bsdtar and busybox all read.
    with tarfile.open(fileobj=output, mode="w|", format=tarfile.GNU_FORMAT) as tar:
        _add_bytes(tar, "MANIFEST", ("\n".join(lines) + "\n").encode(), started)
        entry = tar.gettarinfo(str(snapshot_path), arcname="reticle.db")
        entry.mode = 0o600
        with snapshot_path.open("rb") as handle:
            tar.addfile(entry, handle)

        tar.addfile(_directory_entry("media", started))
        made: set[str] = set()
        for relative in selection.files:
            source = media_root / relative
            try:
                handle = source.open("rb")
            except FileNotFoundError:
                vanished.append(relative)
                continue
            except OSError as error:
                failures.append(f"{relative}: {error}")
                continue
            with handle:
                status = os.fstat(handle.fileno())
                parent = Path(relative).parent
                for ancestor in reversed([parent, *parent.parents][:-1]):
                    name = f"media/{ancestor.as_posix()}"
                    if name not in made:
                        made.add(name)
                        tar.addfile(_directory_entry(name, status.st_mtime))
                entry = tarfile.TarInfo(f"media/{relative}")
                entry.size = status.st_size
                entry.mode = stat.S_IMODE(status.st_mode)
                entry.mtime = int(status.st_mtime)
                entry.uid = status.st_uid
                entry.gid = status.st_gid
                reader = _ExactLength(handle, status.st_size)
                try:
                    tar.addfile(entry, reader)
                except OSError as error:
                    # The stream is beyond repair from here; say so and stop.
                    sys.exit(f"backup: reading {relative} failed part-way ({error}); the archive is incomplete.")
                if reader.padded:
                    message = f"{relative}: shrank by {reader.padded} bytes while it was being copied"
                    if relative in referenced:
                        failures.append(message)
                    else:
                        warn(f"backup: warning: {message} (not referenced by the database; ignored)")
    output.flush()

    warn(
        f"media: {len(selection.files) - len(vanished)} files archived, "
        f"{len(selection.in_flight)} left for the next backup, "
        f"{selection.excluded} temporary or cache entries left out"
    )
    for relative in selection.in_flight:
        warn(
            f"backup: left for the next backup (written in the last {MEDIA_SETTLE_SECONDS // 60} minutes "
            f"and not in the database snapshot — an upload in progress): {relative}"
        )
    for relative in vanished:
        if relative in referenced:
            selection.missing.append(relative)
        # else: an unreferenced file deleted mid-run; nothing was lost.
    for relative in sorted(set(selection.missing)):
        # Not a failure of the backup: the archive is a faithful copy of an
        # installation in which that file is not there (deleted a moment ago
        # by an administrator or the clean-up job, or lost earlier).
        warn(f"backup: warning: the database refers to {relative}, which is not on disk")
    if failures:
        for failure in failures:
            warn(f"backup: ERROR: {failure}")
        sys.exit("backup: files the database refers to could not be copied; this archive must not be trusted.")


# ---------------------------------------------------------------------------
# Is a migration pending? Read-only: it must never create or touch the database.


def schema_state() -> str:
    """One line describing what `python -m app.migrate` would do.

    fresh                  no database yet (or an empty file): first install
    current <rev>          already at this release's schema: nothing to do
    pending <from> <to>    this release would change the schema
    newer <rev>            written by a newer release than this one
    unversioned            has tables but no migration history
    external               not SQLite; this tool cannot look
    """
    url = os.environ.get("RETICLE_DATABASE_URL", DEFAULT_URL)
    if not url.startswith("sqlite:///"):
        return "external"
    path = Path(url[len("sqlite:///"):])
    if not path.exists() or path.stat().st_size == 0:
        return "fresh"
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not tables:
                return "fresh"
            if "alembic_version" not in tables:
                return "unversioned"
            found = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version")}
        finally:
            connection.close()
    except sqlite3.Error as error:
        sys.exit(f"{path}: cannot be read as a SQLite database ({error}).")
    if not found:
        return "unversioned"

    # Imported here so that every other command stays standard-library only.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    location = os.environ.get("RETICLE_MIGRATIONS_DIR", "/app/migrations")
    config = Config()
    config.set_main_option("script_location", location)
    scripts = ScriptDirectory.from_config(config)
    heads = set(scripts.get_heads())
    known = {script.revision for script in scripts.walk_revisions()}

    shown = ",".join(sorted(found))
    if found == heads:
        return f"current {shown}"
    if not found <= known:
        return f"newer {shown}"
    return f"pending {shown} {','.join(sorted(heads))}"


def backup_note() -> Path:
    return live_database().parent / BACKUP_NOTE_NAME


def backup_confirm() -> None:
    """Record that a backup of the database as it is now has just been stored.

    Called by deploy/backup.sh once the archive has been written AND read back
    on the host — not by the container on its own, which cannot know whether
    what it streamed out ever reached a disk.
    """
    revision = verify(live_database())
    note = backup_note()
    partial = note.with_name(note.name + ".partial")
    partial.write_text(f"{int(time.time())} {revision}\n", encoding="ascii")
    os.replace(partial, note)
    print(f"backup recorded: schema revision {revision}")


def backup_is_fresh() -> None:
    """Exit 0 if a confirmed backup of the database as it is now is recent."""
    try:
        limit = int(os.environ.get("RETICLE_MIGRATE_BACKUP_MAX_AGE_MINUTES", BACKUP_FRESH_MINUTES_DEFAULT))
    except ValueError:
        limit = BACKUP_FRESH_MINUTES_DEFAULT
    try:
        written, revision = backup_note().read_text(encoding="ascii").split()
        age_minutes = (time.time() - int(written)) / 60
    except (OSError, ValueError):
        sys.exit("no confirmed backup on record")
    state = schema_state().split()
    current = state[1] if len(state) > 1 else ""
    if revision != current:
        sys.exit(f"the last confirmed backup holds schema revision {revision}, the database is at {current}")
    if not 0 <= age_minutes <= limit:
        sys.exit(f"the last confirmed backup is {age_minutes:.0f} minutes old (limit {limit})")
    print(f"a backup confirmed {age_minutes:.0f} minutes ago holds this database (schema revision {revision})")


USAGE = {
    "snapshot": 1,
    "check": 1,
    "manifest": 1,
    "archive": 2,
    "schema-state": 0,
    "backup-confirm": 0,
    "backup-is-fresh": 0,
}


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in USAGE or len(argv) != 2 + USAGE[argv[1]]:
        sys.exit(__doc__)
    command = argv[1]
    if command == "snapshot":
        snapshot(Path(argv[2]))
    elif command == "check":
        print(f"database check: schema revision {verify(Path(argv[2]))}, integrity ok")
    elif command == "manifest":
        print("\n".join(manifest_lines(Path(argv[2]))))
    elif command == "archive":
        archive(Path(argv[2]), Path(argv[3]))
    elif command == "schema-state":
        print(schema_state())
    elif command == "backup-confirm":
        backup_confirm()
    else:
        backup_is_fresh()


if __name__ == "__main__":
    main(sys.argv)

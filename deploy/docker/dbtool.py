"""Snapshot and verify the SQLite database for backups.

Runs inside the application container, where the database is. A live SQLite
database in WAL mode is three files that are only consistent together and only
at certain instants, so copying ``reticle.db`` while the server runs can produce
a file that opens today and fails next month. SQLite's online-backup API takes
the copy through the database engine instead: it sees a single committed state
and the server keeps serving while it runs.

    dbtool.py snapshot <destination>   consistent copy of the live database
    dbtool.py check <file>             is this a usable Reticle database?
    dbtool.py manifest <file>          a few facts about it, for the archive

Standard library only, on purpose: a backup tool should not depend on the
application importing cleanly.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_URL = "sqlite:////data/reticle.db"


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


def manifest(path: Path) -> None:
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
    print("Reticle backup")
    print(f"created: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"schema-revision: {revision}")
    print(f"image-version: {os.environ.get('RETICLE_IMAGE_VERSION', 'unknown')}")
    for table, count in counts.items():
        print(f"{table}: {count}")


def main(argv: list[str]) -> None:
    if len(argv) != 3 or argv[1] not in {"snapshot", "check", "manifest"}:
        sys.exit(__doc__)
    path = Path(argv[2])
    if argv[1] == "snapshot":
        snapshot(path)
    elif argv[1] == "check":
        print(f"database check: schema revision {verify(path)}, integrity ok")
    else:
        manifest(path)


if __name__ == "__main__":
    main(sys.argv)

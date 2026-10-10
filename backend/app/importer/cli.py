"""Command line for the importer.

::

    python -m app.importer export --site zmb.dozuki.com --out <dir>
    python -m app.importer verify --archive <dir>
    python -m app.importer load --archive <dir> --dry-run
    python -m app.importer load --archive <dir>

``export`` and ``verify`` need neither a Reticle database nor its settings, so
they can run on any machine with network access, today. Only ``load`` imports
the application, and it does so inside the command for exactly that reason.

Credentials come from the environment and nowhere else — never from an
argument, where they would sit in the shell history and the process list — and
are never printed or written to disk.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import TOOL_NAME, TOOL_VERSION
from .archive import Archive, ArchiveError, safe_namespace
from .client import MAX_IMAGE_BYTES, MAX_VIDEO_BYTES, AuthenticationError, ClientError, DozukiClient
from .exporter import DEFAULT_NAMESPACES, Exporter, capture_report, verify_archive

EXIT_OK = 0
EXIT_INCOMPLETE = 1
EXIT_UNUSABLE = 2

ANONYMOUS_WARNING = """\
==============================================================================
WARNING: no credentials given — exporting ANONYMOUSLY.

Only content the site shows to visitors who are not signed in will be
exported. Private, unpublished and team-restricted guides WILL BE MISSING,
and nothing in the result will say which ones.

Set DOZUKI_TOKEN (or DOZUKI_EMAIL and DOZUKI_PASSWORD) and run again to add
them; the export resumes and only fetches what is new. See docs/IMPORT.md.
=============================================================================="""


def _namespaces(value: str) -> tuple[str, ...]:
    names = tuple(part.strip().upper() for part in value.split(",") if part.strip())
    if not names:
        raise argparse.ArgumentTypeError("give at least one namespace, for example CATEGORY,WIKI")
    for name in names:
        try:
            safe_namespace(name)
        except ArchiveError as problem:
            raise argparse.ArgumentTypeError(f"{problem}; namespaces are plain words such as CATEGORY or WIKI") from problem
    return names


def _megabytes(value: str) -> int:
    try:
        number = float(value)
    except ValueError as problem:
        raise argparse.ArgumentTypeError("give a size in megabytes, for example 200") from problem
    if not 0 < number <= 1024 * 1024:
        raise argparse.ArgumentTypeError("the size has to be above 0 MB")
    return int(number * 1024 * 1024)


def _pause(value: str) -> float:
    try:
        number = float(value)
    except ValueError as problem:
        raise argparse.ArgumentTypeError("give a pause in seconds, for example 0.05") from problem
    if not 0 <= number <= 60:
        raise argparse.ArgumentTypeError("the pause has to be between 0 and 60 seconds")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.importer",
        description="Move a facility's own content from a Dozuki site into Reticle, through the vendor's official API.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    export = commands.add_parser(
        "export",
        help="download everything to a directory (needs no Reticle database)",
        description=(
            "Download guides, pages, categories, tags, media and author profiles to a self-contained directory. "
            "Credentials are read from the environment: DOZUKI_TOKEN, or DOZUKI_EMAIL and DOZUKI_PASSWORD "
            "(plus DOZUKI_APP_ID if the site needs one), or DOZUKI_SESSION_COOKIE. Safe to interrupt and re-run."
        ),
    )
    export.add_argument("--site", help="the site to export, for example zmb.dozuki.com")
    export.add_argument("--out", required=True, type=Path, help="directory to write the archive to")
    export.add_argument("--delay", type=float, default=0.25, help="seconds to wait between requests (default 0.25)")
    export.add_argument("--retries", type=int, default=5, help="attempts after a temporary failure (default 5)")
    export.add_argument("--timeout", type=float, default=60.0, help="seconds before a request is given up (default 60)")
    export.add_argument(
        "--namespaces", type=_namespaces, default=DEFAULT_NAMESPACES,
        help=f"wiki namespaces to export, comma-separated (default {','.join(DEFAULT_NAMESPACES)})",
    )
    export.add_argument(
        "--refresh", action="store_true",
        help="fetch every response again instead of reusing what is on disk, ask again for items the site said it does not have, "
        "and download again any image whose markers or picture changed",
    )
    export.add_argument("--verify", action="store_true", help="do not download; re-check the archive in --out and report how old its copies are")
    export.add_argument("--ages", action="store_true", help="with --verify: list the capture time of every single item")
    export.add_argument("--quiet", action="store_true", help="print only warnings and the summary")
    export.add_argument(
        "--max-image-mb", type=_megabytes, default=MAX_IMAGE_BYTES, metavar="MB",
        help=f"largest image file to download (default {MAX_IMAGE_BYTES // (1024 * 1024)})",
    )
    export.add_argument(
        "--max-video-mb", type=_megabytes, default=MAX_VIDEO_BYTES, metavar="MB",
        help=f"largest video file to download (default {MAX_VIDEO_BYTES // (1024 * 1024)})",
    )
    export.add_argument(
        "--allow-private-media-hosts", action="store_true",
        help="also download media from hosts that resolve to private, loopback or link-local addresses (refused by default)",
    )

    verify = commands.add_parser("verify", help="re-check an archive for completeness and report how old its copies are (no network)")
    verify.add_argument("--archive", required=True, type=Path, help="the directory written by export")
    verify.add_argument("--ages", action="store_true", help="list the capture time of every single item")

    load = commands.add_parser(
        "load",
        help="write an archive into the Reticle database",
        description=(
            "Read an export archive and create or update Reticle guides, pages, categories, tags, media and "
            "author accounts. Uses RETICLE_DATABASE_URL and RETICLE_MEDIA_ROOT like the server. Safe to re-run."
        ),
    )
    load.add_argument("--archive", required=True, type=Path, help="the directory written by export")
    load.add_argument(
        "--dry-run", action="store_true",
        help="report what would happen; works on a private copy of the database and writes nothing to the real one or to the media store",
    )
    status = load.add_mutually_exclusive_group()
    status.add_argument(
        "--publish", dest="publish", action="store_true", default=True,
        help="publish guides that were public on the old site, category landing pages, and pages the old site showed to "
        "visitors who were not signed in; everything else becomes a draft (default)",
    )
    status.add_argument("--as-drafts", dest="publish", action="store_false", help="import everything as drafts")
    load.add_argument("--owner-email", help="make this existing Reticle account the author of everything, instead of the original authors")
    load.add_argument("--force", action="store_true", help="overwrite imported content even if it was edited in Reticle afterwards")
    load.add_argument(
        "--markers", choices=("auto", "burned"), default="auto",
        help="auto: turn image markers into editable annotations where the pictures confirm them; burned: keep them drawn into the pictures",
    )
    load.add_argument(
        "--arrow-head", choices=("auto", "start", "end"), default="auto",
        help="which stored end of an arrow carries the head (default: decide per arrow from the picture)",
    )
    load.add_argument(
        "--namespaces", type=_namespaces, default=None,
        help="wiki namespaces to load, comma-separated (default CATEGORY,WIKI,ITEM; INFO holds vendor boilerplate)",
    )
    load.add_argument("--guide", dest="guides", type=int, action="append", help="load only this guide id (repeatable); for a trial run")
    load.add_argument("--report", type=Path, help="where to write the report (default: import-report.md in the archive)")
    load.add_argument(
        "--pause", type=_pause, default=0.05, metavar="SECONDS",
        help="pause after each item written, so the running server's own writes get their turn (default 0.05)",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    environ: dict[str, str] | None = None,
    transport: Any = None,
    sleep: Callable[[float], None] | None = None,
    resolve: Callable[[str], list[str]] | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Run a command and return its exit status.

    ``transport``, ``sleep`` and ``resolve`` exist for the tests, which drive
    the whole command against recorded responses without a network, a clock or
    a name server.
    """
    arguments = build_parser().parse_args(argv)
    environment = os.environ if environ is None else environ
    if arguments.command == "export":
        if arguments.verify:
            return run_verify(arguments.out, out, arguments.ages)
        if not arguments.site:
            out("export needs --site, for example --site zmb.dozuki.com")
            return EXIT_UNUSABLE
        return run_export(arguments, environment, transport, sleep, resolve, out)
    if arguments.command == "verify":
        return run_verify(arguments.archive, out, arguments.ages)
    return run_load(arguments, out, sleep)


def run_export(
    arguments: argparse.Namespace,
    environment: Any,
    transport: Any,
    sleep: Callable[[float], None] | None,
    resolve: Callable[[str], list[str]] | None,
    out: Callable[[str], None],
) -> int:
    token = (environment.get("DOZUKI_TOKEN") or "").strip() or None
    email = (environment.get("DOZUKI_EMAIL") or "").strip() or None
    password = environment.get("DOZUKI_PASSWORD") or None
    app_id = (environment.get("DOZUKI_APP_ID") or "").strip() or None
    cookie = (environment.get("DOZUKI_SESSION_COOKIE") or "").strip() or None
    progress = (lambda message: None) if arguments.quiet else out

    def log(message: str) -> None:
        (out if message.startswith(("WARNING", "  FAILED")) else progress)(message)

    options: dict[str, Any] = {
        "token": token, "app_id": app_id, "cookie": cookie, "transport": transport, "delay": arguments.delay,
        "retries": arguments.retries, "timeout": arguments.timeout, "log": progress,
        "allow_private_media_hosts": arguments.allow_private_media_hosts,
    }
    if sleep is not None:
        options["sleep"] = sleep
    if resolve is not None:
        options["resolve"] = resolve
    try:
        client = DozukiClient(arguments.site, **options)
    except ValueError as problem:
        out(str(problem))
        return EXIT_UNUSABLE

    with client:
        try:
            if token is None and email and password:
                client.login(email, password)
                out(f"Signed in to {client.host} as {email}.")
            elif token is not None:
                out(f"Using the API token from DOZUKI_TOKEN for {client.host}.")
            elif cookie is not None:
                out(f"Using the browser session cookie from DOZUKI_SESSION_COOKIE for {client.host} (an undocumented route; see docs/IMPORT.md).")
            else:
                out(ANONYMOUS_WARNING)
            exporter = Exporter(
                client, Archive(arguments.out), namespaces=arguments.namespaces, refresh=arguments.refresh, log=log,
                max_image_bytes=arguments.max_image_mb, max_video_bytes=arguments.max_video_mb,
            )
            exporter.run()
        except AuthenticationError as problem:
            out(f"STOPPED: {problem}")
            out("Whatever was downloaded so far is kept; the next run resumes from it.")
            return EXIT_UNUSABLE
        except (ClientError, ArchiveError) as problem:
            out(f"STOPPED: {problem}")
            return EXIT_UNUSABLE

    out("")
    out(f"Export of {client.host} written to {arguments.out}")
    for kind, bucket in exporter.counts().items():
        out(f"  {kind + ':':<17}" + ", ".join(f"{count} {status}" for status, count in sorted(bucket.items())))
    out(f"  requests made:   {client.requests_made}")
    if not client.authenticated:
        out("  NOTE: exported anonymously — private and unpublished content is NOT included.")
    for warning in exporter.warnings:
        out(f"  WARNING: {warning}")
    failures = exporter.failures()
    if failures:
        out(f"\n{len(failures)} item(s) FAILED:")
        for key, error in sorted(failures.items()):
            out(f"  {key}: {error}")
        out("Run the same command again to retry them; everything else is skipped.")
        return EXIT_INCOMPLETE
    out("Nothing failed. Run `python -m app.importer verify --archive <dir>` before relying on it.")
    return EXIT_OK


def run_verify(root: Path, out: Callable[[str], None], every_item: bool = False) -> int:
    archive = Archive(root)
    problems, stats = verify_archive(archive)
    out(
        f"Checked {root}: {stats['guides']} guides, {stats['pages']} pages, "
        f"{stats['images']} image and {stats['videos']} video references, {stats['files_checked']} file checksums."
    )
    try:
        for line in capture_report(archive, every_item=every_item):
            out(line)
    except ArchiveError:
        pass  # no manifest: verify_archive has said so already
    if problems:
        out(f"{len(problems)} problem(s):")
        for problem in problems:
            out(f"  {problem}")
        return EXIT_INCOMPLETE
    out("The archive is complete: every guide and page is present and every media file matches its checksum.")
    return EXIT_OK


def sqlite_file(url: str) -> Path | None:
    """The file behind a SQLite database URL, or ``None`` for any other database."""
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database or parsed.database == ":memory:" or parsed.database.startswith("file:"):
        return None
    return Path(parsed.database)


def snapshot_database(source: Path, target: Path) -> None:
    """Copy a live SQLite database with SQLite's own online backup.

    The source is opened read-only and is only ever read: under WAL, which is
    how Reticle runs, that neither waits for the server's writes nor makes them
    wait. The copy is consistent as of one moment, whatever is being written
    meanwhile.
    """
    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=30)) as live:
        with closing(sqlite3.connect(target)) as copy:
            live.backup(copy)


def run_load(arguments: argparse.Namespace, out: Callable[[str], None], sleep: Callable[[float], None] | None = None) -> int:
    try:
        archive = Archive(arguments.archive)
        archive.manifest()
    except ArchiveError as problem:
        out(str(problem))
        return EXIT_UNUSABLE

    from sqlalchemy.engine import make_url

    from .. import db, migrate
    from ..settings import get_settings
    from .loader import DEFAULT_LOAD_NAMESPACES, LoadError, Loader, LoadOptions

    try:
        migrate.assert_current(db.engine)
    except migrate.SchemaError as problem:
        out(str(problem))
        return EXIT_UNUSABLE

    settings = get_settings()
    options = LoadOptions(
        publish=arguments.publish,
        dry_run=arguments.dry_run,
        force=arguments.force,
        owner_email=arguments.owner_email,
        markers=arguments.markers,
        arrow_head=arguments.arrow_head,
        namespaces=arguments.namespaces or DEFAULT_LOAD_NAMESPACES,
        only_guides=frozenset(arguments.guides) if arguments.guides else None,
        pause=arguments.pause,
    )
    described = make_url(settings.database_url).render_as_string(hide_password=True)
    extras: dict[str, Any] = {} if sleep is None else {"sleep": sleep}
    scratch: Path | None = None
    engine = db.engine
    try:
        if arguments.dry_run:
            # A dry run must not take the live database's write lock even once:
            # on SQLite that lock is the only one there is, and the server's
            # logins and autosaves all need it.
            live = sqlite_file(settings.database_url)
            if live is not None:
                try:
                    scratch = Path(tempfile.mkdtemp(prefix="reticle-dry-run-"))
                    snapshot_database(live, scratch / "snapshot.db")
                except (sqlite3.Error, OSError) as problem:
                    raise LoadError(
                        f"The database could not be copied for the dry run ({problem}). The copy goes to the temporary "
                        f"directory (TMPDIR, now {os.environ.get('TMPDIR') or 'unset'}), which has to exist, be writable and "
                        "have room for one copy of the database file."
                    ) from problem
                engine = db.build_engine(f"sqlite:///{scratch / 'snapshot.db'}")
                settings = settings.model_copy(update={"media_root": scratch / "media"})
                options = replace(options, pause=0.0)
                described += " (dry run on a private snapshot copy; the database itself was only read)"
                out(f"Dry run: working on a snapshot copy of the database in {scratch}; it is deleted afterwards.")
            else:
                described += " (dry run in one transaction that was rolled back)"
        writers, readers = db.session_factories(engine)
        if arguments.dry_run and scratch is None:
            # Not a SQLite file (PostgreSQL, say): one transaction, never
            # committed. There it holds row locks on what it touches only.
            with writers() as session:
                loader = Loader(session, archive, options, settings, log=out, commit=False, **extras)
                report = loader.run()
        else:
            with writers() as session, readers() as reader:
                loader = Loader(session, archive, options, settings, log=out, reader=reader, **extras)
                report = loader.run()
    except LoadError as problem:
        out(str(problem))
        return EXIT_UNUSABLE
    finally:
        if scratch is not None:
            engine.dispose()
            shutil.rmtree(scratch, ignore_errors=True)

    report.header["Database"] = described
    target = arguments.report or arguments.archive / ("import-report-dry-run.md" if arguments.dry_run else "import-report.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report.markdown(), encoding="utf-8")

    out("")
    out("DRY RUN — nothing was written to Reticle." if arguments.dry_run else "Load finished.")
    out(report.summary())
    if not arguments.dry_run:
        out(f"  database write lock: {loader.lock_summary()}")
    out(f"Full report: {target}")
    return EXIT_INCOMPLETE if report.failed else EXIT_OK

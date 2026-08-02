"""The command line for getting data out and putting it back.

    python -m app.portability export --out ./reticle-export
    python -m app.portability export --archive ./reticle-export.tar.gz
    python -m app.portability restore --from ./reticle-export.tar.gz
    python -m app.portability publish --out ./site

A command rather than only an endpoint, for two reasons. An export is the thing
somebody wants when the application will not start, and an HTTP call needs it to
be running. And a scheduled export belongs in cron next to the database backup,
where it needs no session, no cookie and no browser.

Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import exporter
from .db import SessionLocal, init_db
from .importer.client import MigrationError
from .importer.reticle import read_export, restore
from .settings import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.portability",
        description="Export the whole corpus, or restore one into an empty database.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    out = commands.add_parser("export", help="Write everything out.")
    destination = out.add_mutually_exclusive_group(required=True)
    destination.add_argument(
        "--out", type=Path, help="Write a directory: JSON plus a media folder."
    )
    destination.add_argument("--archive", type=Path, help="Write a single .tar.gz.")

    site = commands.add_parser(
        "publish",
        help="Render the published corpus as plain HTML: an offline, archival copy "
        "that needs no application, no database and no network.",
    )
    site.add_argument("--out", type=Path, required=True, help="Directory to write the site into.")

    back = commands.add_parser("restore", help="Read an export into an empty database.")
    back.add_argument(
        "--from", dest="source", type=Path, required=True, help="Directory or .tar.gz."
    )
    back.add_argument(
        "--placeholder-password",
        default=None,
        help="Password every restored account is given. Omit for an unusable one, "
        "which is the safe default: everybody signs in again after a restore.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_db()
    settings = get_settings()
    db = SessionLocal()

    try:
        if args.command == "export":
            if args.out is not None:
                document = exporter.write_to_directory(db, settings, args.out)
                counts = document["reticleExport"]["counts"]
                print(f"Wrote {args.out}")
            else:
                args.archive.parent.mkdir(parents=True, exist_ok=True)
                with args.archive.open("wb") as handle:
                    for chunk in exporter.stream_archive(db, settings):
                        handle.write(chunk)
                counts = exporter.build_document(db, settings)["reticleExport"]["counts"]
                print(f"Wrote {args.archive}")
            for name, value in counts.items():
                print(f"  {name:<16} {value}")
            return 0

        if args.command == "publish":
            from .static_site import publish

            report = publish(db, settings, args.out)
            print(report.to_text())
            print(f"Wrote {args.out}")
            return 0

        document, files = read_export(args.source)
        report = restore(db, settings, document, files, args.placeholder_password)
        print(report.to_text())
        # A restore that lost a file is not a restore. It exits non-zero so a
        # script cannot treat "finished" as "correct".
        return 0 if report.intact else 1

    except MigrationError as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

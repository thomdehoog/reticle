#!/usr/bin/env bash
#
# The inner half of a facility backup: one PostgreSQL dump of the database
# named by RETICLE_DATABASE_URL, which must already be in the environment.
#
#     pg-dump-facility.sh /path/to/output.dump
#
# You almost certainly want backup-facility.sh instead. That one takes a
# facility slug, loads its environment as the `reticle` account, and calls this.
# This half is separate because the database URL — password included — lives in
# a file only `reticle` can read, so the parsing has to happen on that side of
# the `sudo`.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

set -euo pipefail

OUT="${1:-}"
if [[ -z "$OUT" ]]; then
    echo "usage: $0 <output file>" >&2
    exit 64
fi

URL="${RETICLE_DATABASE_URL:-}"
if [[ -z "$URL" ]]; then
    echo "RETICLE_DATABASE_URL is not set. Nothing to dump." >&2
    exit 64
fi

# postgresql[+driver]://user:password@host[:port]/database
#
# The password is picked out and handed over in the environment rather than on
# the command line. Anyone on the machine can read /proc/<pid>/cmdline, and a
# database password sitting there for the length of a dump is a password
# anybody logged in that minute has.
if [[ ! "$URL" =~ ^postgresql(\+[a-z0-9_]+)?://([^:/@]+):([^@]*)@([^:/@]+)(:([0-9]+))?/([^?]+) ]]; then
    cat >&2 <<MALFORMED
Cannot read RETICLE_DATABASE_URL as a PostgreSQL connection string.

Expected  postgresql+psycopg://user:password@host/database
Note that a password containing percent-escapes (%40 for @, and so on) is not
decoded here. Rewrite it without escapes, or take the dump by hand.
MALFORMED
    exit 65
fi

DB_USER="${BASH_REMATCH[2]}"
DB_PASSWORD="${BASH_REMATCH[3]}"
DB_HOST="${BASH_REMATCH[4]}"
DB_PORT="${BASH_REMATCH[6]:-5432}"
DB_NAME="${BASH_REMATCH[7]}"

# 0600 before a single byte is written. The dump is every guide, every account
# and every password hash in the facility.
umask 077

# --format=custom, not plain SQL. It is compressed, it restores selectively with
# pg_restore, and — the part that matters here — it carries the sequences, the
# grants and the alembic_version row, which the application-level export in
# `app.portability` does not. That export is a portable corpus; this is the
# database.
#
# --no-password makes a missing or wrong password an immediate error instead of
# a prompt nobody is there to answer, which is the difference between a deploy
# that fails and a deploy that hangs until the job times out.
PGPASSWORD="$DB_PASSWORD" pg_dump \
    --format=custom \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname="$DB_NAME" \
    --no-password \
    --file="$OUT"

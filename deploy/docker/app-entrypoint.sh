#!/bin/sh
# Entrypoint of the Reticle application image.
#
#   serve            (default) migrate the database, then run the API
#   migrate          create or upgrade the schema and exit
#   schema-state     say whether this release would migrate the database
#   seed [--demo]    create the first administrator / demo content and exit
#   backup-stream    write a consistent backup (tar) to stdout
#   backup-confirm   record that the backup just streamed was stored safely
#   restore-stream   replace database and media from a tar on stdin
#   anything else    is executed as given, e.g. `python -m app.importer ...`
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# Nobody but this user has any business reading a guide draft, a password hash
# or a backup in the making.
umask 077

DATA_DIR=/data
MEDIA_DIR="${RETICLE_MEDIA_ROOT:-$DATA_DIR/media}"
: "${TMPDIR:=$DATA_DIR/tmp}"
export TMPDIR
DBTOOL=/usr/local/lib/reticle/dbtool.py

# Caches the application keeps on the data volume OUTSIDE the media root.
# By default there are none: the rendered-PDF cache is <media root>/.pdf-cache,
# which a backup leaves out (the rules are at the top of dbtool.py) and which
# a restore removes together with the media directory it replaces. This list
# is for a cache that has been moved elsewhere (RETICLE_PDF_CACHE_DIR): a
# restore empties these directories, because a cached PDF of "version 7" must
# not survive the arrival of a database in which version 7 is a different
# document. Only directories under /data are touched, and whatever is listed
# here must be safe to delete at any time.
CACHE_DIRS="$DATA_DIR/cache $DATA_DIR/pdf-cache $DATA_DIR/.pdf-cache ${RETICLE_PDF_CACHE_DIR:-}"

# A release that changes the database schema cannot be undone by starting the
# old image again: the old release cannot read what the new one wrote. So a
# migration that would CHANGE an existing database only runs when there is a
# way back — a backup that deploy/backup.sh confirmed within the last hour —
# or when the operator has said so explicitly (RETICLE_ALLOW_MIGRATE=1, which
# is what deploy/upgrade.sh sets after taking its own backup). A new
# installation has nothing to lose and a database already at this release's
# schema has nothing to migrate; neither is ever held up here.
guard_migration() {
    state="$(python "$DBTOOL" schema-state)" || {
        echo "reticle: could not determine the state of the database (see above); nothing was changed." >&2
        exit 1
    }
    case "$state" in
    pending\ *) ;;
    *) return 0 ;;
    esac
    # shellcheck disable=SC2086  # deliberately split: "pending <from> <to>"
    set -- $state
    if [ "${RETICLE_ALLOW_MIGRATE:-}" = "1" ]; then
        echo "reticle: migrating the database from schema revision $2 to $3 (RETICLE_ALLOW_MIGRATE=1)." >&2
        return 0
    fi
    if evidence="$(python "$DBTOOL" backup-is-fresh 2>&1)"; then
        echo "reticle: migrating the database from schema revision $2 to $3: $evidence." >&2
        return 0
    fi
    cat >&2 <<MESSAGE

reticle: NOT STARTED, and nothing has been changed.

This release has to migrate the database (schema revision $2 -> $3). A
migration cannot be undone by going back to the previous image, so it is not
run without a fresh backup — and there is none on record ($evidence).

  To upgrade:     deploy/upgrade.sh
                  It takes a backup, migrates, and starts this release.
  To stay put:    set RETICLE_VERSION in .env back to the release you were
                  running, then: docker compose up -d
                  The database is exactly as that release left it.

(By hand: 'deploy/backup.sh' and then 'docker compose up -d' within the hour
does the same; RETICLE_ALLOW_MIGRATE=1 in the environment of 'docker compose
up -d' migrates without asking for a backup at all.)
MESSAGE
    exit 1
}

migrate() {
    guard_migration
    python -m app.migrate
}

command="${1:-serve}"
[ "$#" -gt 0 ] && shift

case "$command" in
serve)
    mkdir -p "$TMPDIR" "$MEDIA_DIR"

    # Uploads are spooled here on their way to the media root. Whatever is left
    # over belongs to a process that no longer exists: this container is the
    # only writer and it is only now starting.
    find "$TMPDIR" -mindepth 1 -maxdepth 1 -mmin +60 -exec rm -rf {} + 2>/dev/null || true

    # The server refuses to start on a schema it does not recognise, and it does
    # not migrate for itself because each worker would try. This is the one
    # place that runs before any worker exists, so it is done here.
    if ! migrate; then
        cat >&2 <<'MESSAGE'

reticle: the database could not be brought to the schema this release expects,
so the server has not been started. The reason is above. If it says the
database was written by a NEWER release, you have gone back to an older image:
the newer one already migrated the database, and an older release cannot read
it. Return to the newer release, or restore the backup that was taken before
the upgrade (deploy/restore.sh; docs/MAINTENANCE.md, section 3).
MESSAGE
        exit 1
    fi

    # --no-proxy-headers: uvicorn must not rewrite the client address from
    # X-Forwarded-For on its own. RETICLE_TRUSTED_PROXIES is the only thing that
    # decides whose header is believed; the login throttle and the audit log
    # both depend on that.
    exec python -m uvicorn app.main:app \
        --host 0.0.0.0 --port 8000 \
        --workers "${RETICLE_WORKERS:-2}" \
        --no-proxy-headers --no-server-header --no-access-log \
        --timeout-graceful-shutdown 20
    ;;
migrate)
    mkdir -p "$TMPDIR" "$MEDIA_DIR"
    migrate
    ;;
schema-state)
    exec python "$DBTOOL" schema-state
    ;;
seed)
    exec python -m app.seed "$@"
    ;;
backup-stream)
    # The archive goes to stdout, so everything a human should read goes to
    # stderr. Database first, media second: a media file is on disk before the
    # row that refers to it is committed, so everything the snapshot refers to
    # is there to be copied. Which files are taken from the media root — and
    # why an upload in progress is not one of them — is at the top of dbtool.py.
    mkdir -p "$TMPDIR" "$MEDIA_DIR"
    work="$(mktemp -d "$TMPDIR/backup.XXXXXX")"
    trap 'rm -rf "$work"' EXIT INT TERM
    python "$DBTOOL" snapshot "$work/reticle.db" >&2
    python "$DBTOOL" archive "$work/reticle.db" "$MEDIA_DIR"
    ;;
backup-confirm)
    # Called by deploy/backup.sh after the archive has been written and read
    # back on the host. See guard_migration above for what it is evidence of.
    exec python "$DBTOOL" backup-confirm >&2
    ;;
restore-stream)
    # The caller (deploy/restore.sh) has stopped the server. Nothing here can
    # verify that, and replacing a database under a running server is exactly
    # the corruption the backup exists to recover from.
    mkdir -p "$TMPDIR"
    work="$(mktemp -d "$TMPDIR/restore.XXXXXX")"
    trap 'rm -rf "$work"' EXIT INT TERM
    tar -xf - -C "$work" --no-same-owner
    [ -f "$work/reticle.db" ] || { echo "restore: the archive contains no reticle.db" >&2; exit 1; }
    [ -d "$work/media" ] || mkdir "$work/media"
    python "$DBTOOL" check "$work/reticle.db" >&2

    # Everything up to here was harmless. From here the live data is replaced;
    # each step is a rename within one filesystem, so there is no moment with
    # half a database. The -wal and -shm files belong to the OLD database:
    # left behind, SQLite would replay them into the restored one.
    rm -f "$DATA_DIR/reticle.db-wal" "$DATA_DIR/reticle.db-shm" "$DATA_DIR/.last-backup"
    mv -f "$work/reticle.db" "$DATA_DIR/reticle.db"
    rm -rf "$MEDIA_DIR.replaced"
    if [ -d "$MEDIA_DIR" ]; then mv "$MEDIA_DIR" "$MEDIA_DIR.replaced"; fi
    mv "$work/media" "$MEDIA_DIR"
    rm -rf "$MEDIA_DIR.replaced"
    # Caches describe the database that has just been replaced.
    for cache in $CACHE_DIRS; do
        case "$cache" in
        "$MEDIA_DIR" | "$MEDIA_DIR"/*) ;; # replaced a moment ago, as a whole
        "$DATA_DIR"/?*) if [ -d "$cache" ]; then find "$cache" -mindepth 1 -delete; fi ;;
        esac
    done
    echo "restore: database and media replaced." >&2
    ;;
*)
    exec "$command" "$@"
    ;;
esac

#!/bin/sh
# Entrypoint of the Reticle application image.
#
#   serve            (default) migrate the database, then run the API
#   migrate          create or upgrade the schema and exit
#   seed [--demo]    create the first administrator / demo content and exit
#   backup-stream    write a consistent backup (tar) to stdout
#   restore-stream   replace database and media from a tar on stdin
#   anything else    is executed as given, e.g. `python -m app.importer ...`
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# Nobody but this user has any business reading a guide draft, a password hash
# or a backup in the making.
umask 077

DATA_DIR=/data
: "${TMPDIR:=$DATA_DIR/tmp}"
export TMPDIR

command="${1:-serve}"
[ "$#" -gt 0 ] && shift

case "$command" in
serve)
    mkdir -p "$TMPDIR" "${RETICLE_MEDIA_ROOT:-$DATA_DIR/media}"

    # Uploads are spooled here on their way to the media root. Whatever is left
    # over belongs to a process that no longer exists: this container is the
    # only writer and it is only now starting.
    find "$TMPDIR" -mindepth 1 -maxdepth 1 -mmin +60 -exec rm -rf {} + 2>/dev/null || true

    # The server refuses to start on a schema it does not recognise, and it does
    # not migrate for itself because each worker would try. This is the one
    # place that runs before any worker exists, so it is done here: an upgrade
    # is "start the new image".
    if ! python -m app.migrate; then
        cat >&2 <<'MESSAGE'

reticle: the database could not be brought to the schema this release expects,
so the server has not been started. The error is above. If you have just gone
BACK to an older release, this is expected: the newer one already migrated the
database, and an older release cannot read it. Restore the backup that was
taken before the upgrade (deploy/restore.sh), or return to the newer release.
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
    exec python -m app.migrate
    ;;
seed)
    exec python -m app.seed "$@"
    ;;
backup-stream)
    # The archive goes to stdout, so everything a human should read goes to
    # stderr. Database first, media second: media files are written once under
    # generated names and never modified, so the media set is then a superset
    # of what the database snapshot refers to. The other order could produce a
    # database that mentions a photograph the archive does not contain.
    mkdir -p "$TMPDIR"
    work="$(mktemp -d "$TMPDIR/backup.XXXXXX")"
    trap 'rm -rf "$work"' EXIT INT TERM
    python /usr/local/lib/reticle/dbtool.py snapshot "$work/reticle.db" >&2
    python /usr/local/lib/reticle/dbtool.py manifest "$work/reticle.db" > "$work/MANIFEST"
    mkdir -p "$DATA_DIR/media"
    tar -cf - -C "$work" MANIFEST reticle.db -C "$DATA_DIR" media
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
    python /usr/local/lib/reticle/dbtool.py check "$work/reticle.db" >&2

    # Everything up to here was harmless. From here the live data is replaced;
    # each step is a rename within one filesystem, so there is no moment with
    # half a database. The -wal and -shm files belong to the OLD database:
    # left behind, SQLite would replay them into the restored one.
    rm -f "$DATA_DIR/reticle.db-wal" "$DATA_DIR/reticle.db-shm"
    mv -f "$work/reticle.db" "$DATA_DIR/reticle.db"
    rm -rf "$DATA_DIR/media.replaced"
    [ -d "$DATA_DIR/media" ] && mv "$DATA_DIR/media" "$DATA_DIR/media.replaced"
    mv "$work/media" "$DATA_DIR/media"
    rm -rf "$DATA_DIR/media.replaced"
    echo "restore: database and media replaced." >&2
    ;;
*)
    exec "$command" "$@"
    ;;
esac

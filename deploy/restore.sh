#!/bin/sh
# Replace everything in a Reticle installation with the contents of a backup.
#
#   deploy/restore.sh backups/reticle-20261010T023000Z.tar.gz
#   deploy/restore.sh --yes <archive>             # no question asked (scripts)
#   deploy/restore.sh --no-safety-backup <archive>
#
# What happens, in order:
#   1. the archive is checked — unreadable archives stop here, harmlessly;
#   2. the CURRENT state is backed up first (a restore is the one operation
#      that destroys data on purpose, and "the wrong archive" is a real mistake);
#   3. the site goes down;
#   4. database and media are replaced;
#   5. the site comes back up; if the backup is from an older release, its
#      schema is upgraded on the way.
#
# A backup taken by a NEWER release than the one installed cannot be used:
# the server will refuse to start and say so. Install that release first.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

assume_yes=false
safety_backup=true
archive=""
for argument in "$@"; do
    case "$argument" in
    --yes | -y) assume_yes=true ;;
    --no-safety-backup) safety_backup=false ;;
    -*) die "unknown option $argument" ;;
    *) archive="$argument" ;;
    esac
done
[ -n "$archive" ] || die "usage: restore.sh [--yes] [--no-safety-backup] <archive.tar.gz>"
[ -f "$archive" ] || die "no such file: $archive"

gzip -t "$archive" || die "$archive is not a readable gzip archive"
listing="$(gzip -dc "$archive" | tar -tf -)" || die "$archive cannot be listed"
printf '%s\n' "$listing" | grep -qx 'reticle.db' ||
    die "$archive contains no reticle.db — it is not a Reticle backup"
files="$(printf '%s\n' "$listing" | grep -c '^media/.*[^/]$' || true)"

echo "Archive:  $archive"
gzip -dc "$archive" | tar -xOf - MANIFEST 2>/dev/null | sed 's/^/          /' || true
echo "          $files media files"
echo
echo "This REPLACES the database and all uploaded media of the installation in"
echo "  $RETICLE_HOME"
echo "with the contents of that archive. Everything written since it was taken"
echo "will be gone from the live site."

if [ "$assume_yes" != true ]; then
    [ -t 0 ] || die "refusing to restore without confirmation; pass --yes when running unattended"
    printf "Type 'restore' to continue: "
    read -r answer
    [ "$answer" = "restore" ] || die "not confirmed; nothing was changed"
fi

if [ "$safety_backup" = true ]; then
    echo "Backing up the current state first..."
    "$(dirname -- "$0")/backup.sh" ||
        die "could not back up the current state, so nothing was changed. If the current data is already lost or unreadable, run again with --no-safety-backup"
fi

echo "Stopping the site..."
compose stop web app

echo "Restoring..."
status="$({ gzip -dc "$archive" | {
    code=0
    compose run --rm --no-deps -T app reticle-entrypoint restore-stream || code=$?
    echo "$code" >&3
}; } 3>&1)"
if [ "$status" != "0" ]; then
    echo "The restore failed (exit $status). If the message above is about the archive," >&2
    echo "the live data has not been touched: 'docker compose up -d' brings the site back as it was." >&2
    exit 1
fi

echo "Starting the site..."
compose up -d --wait || die "the data was restored but the site did not come back healthy; see 'docker compose logs app'"
echo "Restored from $archive. Everybody has to sign in again only if RETICLE_SECRET_KEY differs from the one in use when the backup was taken."

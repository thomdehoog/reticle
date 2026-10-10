#!/bin/sh
# Back up a running Reticle: the database and every uploaded file, in one
# timestamped archive.
#
#   deploy/backup.sh                 # into RETICLE_BACKUP_DIR (default ./backups)
#   deploy/backup.sh /mnt/nas/reticle
#
# Safe while people are working. The database is copied through SQLite's
# online-backup API inside the application container — never by copying
# reticle.db, which in WAL mode is one of three files that are only consistent
# together. The site stays up throughout.
#
# Archives older than RETICLE_BACKUP_KEEP_DAYS (default 14) are then removed
# from the same directory — but only after this run has succeeded, so a
# backup that has been failing for a month does not eat its predecessors.
#
# The archive does NOT contain .env. Keep a copy of that somewhere else that
# is not next to the backups: together they are the whole installation.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

destination="${1:-$(setting RETICLE_BACKUP_DIR "$RETICLE_HOME/backups")}"
keep_days="$(setting RETICLE_BACKUP_KEEP_DAYS 14)"
case "$destination" in
/*) ;;
*) destination="$RETICLE_HOME/$destination" ;;
esac
case "$keep_days" in
'' | *[!0-9]*) die "RETICLE_BACKUP_KEEP_DAYS must be a whole number of days, not '$keep_days'" ;;
esac

# The archive holds every guide, including drafts, and every password hash.
umask 077
mkdir -p "$destination"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="$destination/reticle-$stamp.tar.gz"
partial="$archive.partial"
trap 'rm -f "$partial"' EXIT INT TERM

# `set -e` does not see a failure on the left of a pipe, and POSIX sh has no
# pipefail, so the container's exit status is carried out through a file
# descriptor instead of being lost behind gzip's.
status="$({ {
    code=0
    in_app reticle-entrypoint backup-stream </dev/null || code=$?
    echo "$code" >&3
} | gzip >"$partial"; } 3>&1)"
[ "$status" = "0" ] || die "the backup failed inside the container (exit $status); nothing was written"

# An archive that cannot be read back is not a backup. Check it now, while
# someone is looking, rather than on the day it is needed.
gzip -t "$partial" || die "the archive is corrupt"
listing="$(gzip -dc "$partial" | tar -tf -)" || die "the archive cannot be listed"
printf '%s\n' "$listing" | grep -qx 'reticle.db' || die "the archive contains no database"

mv "$partial" "$archive"
trap - EXIT INT TERM

files="$(printf '%s\n' "$listing" | grep -c '^media/.*[^/]$' || true)"
size="$(du -h "$archive" | cut -f1)"
echo "backup written: $archive ($size, $files media files)"

if [ "$keep_days" -gt 0 ]; then
    find "$destination" -maxdepth 1 -type f -name 'reticle-*.tar.gz' -mtime "+$keep_days" -exec rm -f {} +
fi

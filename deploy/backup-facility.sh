#!/usr/bin/env bash
#
# Back up one facility: the database, and the media with it.
#
#     sudo ./backup-facility.sh zmb              # -> backups/backup-<stamp>.*
#     sudo ./backup-facility.sh zmb pre-migrate  # what migrate-all.sh calls
#
# Two files come out, and both are needed, because neither is a superset of the
# other:
#
#   <label>-<stamp>.dump      pg_dump --format=custom. The database exactly as
#                             it is — sequences, grants, the alembic_version
#                             row. Restores with pg_restore. Contains no media,
#                             because the pictures are files on disk.
#
#   <label>-<stamp>.tar.gz    `python -m app.portability export --archive`. The
#                             media, plus the same content as documented JSON
#                             with a SHA-256 per file. Restores into any engine
#                             and into a different version of Reticle. This is
#                             the one to hand a facility that is leaving.
#
# Everything lands in that facility's own backups/ directory, mode 0700, so a
# backup is a complete corpus that restores on its own and nobody else on the
# machine can read it.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

set -euo pipefail

# shellcheck source=deploy/reticle-lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reticle-lib.sh"

SLUG="${1:-}"
LABEL="${2:-backup}"

if [[ -z "$SLUG" ]]; then
    echo "usage: $0 <slug> [label]" >&2
    exit 64
fi

FACILITY_DIR="$(reticle_facility_dir "$SLUG")"
ENV_FILE="$(reticle_env_file "$SLUG")"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Every check and every write below goes through the service account. This
# script is run both by an operator with root and by the deploy account during a
# release, and the deploy account cannot so much as stat a file inside a
# facility directory — they are 0750 and owned by `reticle`.
if ! run_as_reticle test -f "$ENV_FILE"; then
    echo "No environment file at $ENV_FILE. Is '$SLUG' a facility on this host?" >&2
    exit 66
fi

BACKUP_DIR="$FACILITY_DIR/backups"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# 0700. A backup holds every password hash and — in the case of the archive —
# every photograph, so a directory any local account can list is a directory
# that has already leaked.
run_as_reticle mkdir -p -m 700 "$BACKUP_DIR"

echo "==> $SLUG: database"
run_as_reticle --env "$ENV_FILE" "$SCRIPT_DIR/pg-dump-facility.sh" \
    "$BACKUP_DIR/$LABEL-$STAMP.dump"

echo "==> $SLUG: media and portable corpus"
run_as_reticle --env "$ENV_FILE" "$(reticle_venv_bin)/python" -m app.portability \
    export --archive "$BACKUP_DIR/$LABEL-$STAMP.tar.gz" >/dev/null

echo "==> $SLUG: done"
run_as_reticle ls -lh "$BACKUP_DIR/$LABEL-$STAMP.dump" "$BACKUP_DIR/$LABEL-$STAMP.tar.gz"

# Old backups are pruned here rather than by the deploy, because this is already
# running as the only account that can read the directory. A `find` over
# /opt/reticle/facilities run by the deploy account exits non-zero on the first
# "permission denied", and under `set -e` that fails a deploy which has already
# succeeded.
run_as_reticle find "$BACKUP_DIR" -maxdepth 1 -type f \
    -name "$LABEL-*" -mtime +30 -delete

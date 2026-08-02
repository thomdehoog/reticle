#!/usr/bin/env bash
#
# Run pending migrations across every facility, after backing each one up.
#
#     sudo ./migrate-all.sh            # migrate all
#     sudo ./migrate-all.sh --dry-run  # show what would run, change nothing
#
# This is the cost of a database per facility, stated plainly: migrations are a
# loop rather than a single command. The loop is short and it is worth it — the
# thing it buys is that no query can reach another facility's data, because the
# connection does not contain it.
#
# The important property is the failure behaviour. A failure on facility seven
# must not leave one to six on a new schema with old code, so this stops at the
# first failure and reports exactly where it stopped, rather than carrying on
# and reporting a tally at the end.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/reticle-lib.sh
. "$SCRIPT_DIR/reticle-lib.sh"

DRY_RUN=false
case "${1:-}" in
    "") ;;
    --dry-run) DRY_RUN=true ;;
    *)
        # An unrecognised flag must not fall through to the real thing. The
        # whole purpose of --dry-run is "change nothing", so a typo like
        # --dryrun silently migrating every facility is the worst possible
        # failure this script could have.
        echo "Unknown argument '${1}'. Use --dry-run, or no arguments to migrate." >&2
        exit 64
        ;;
esac

shopt -s nullglob
FACILITIES=("$RETICLE_ROOT"/facilities/*/)
if [[ ${#FACILITIES[@]} -eq 0 ]]; then
    echo "No facilities under $RETICLE_ROOT/facilities." >&2
    exit 1
fi

ALEMBIC="$(reticle_venv_bin)/alembic"

echo "==> ${#FACILITIES[@]} facilities"

for dir in "${FACILITIES[@]}"; do
    slug="$(basename "$dir")"
    env_file="$dir/env"

    # Asked as `reticle`, because the deploy account cannot see inside a
    # facility directory at all — see run_as_reticle.
    if ! run_as_reticle test -f "$env_file"; then
        echo "!! $slug has no env file; refusing to guess. Stopping." >&2
        exit 1
    fi

    if ! current=$(run_as_reticle --env "$env_file" "$ALEMBIC" current 2>/dev/null | tail -1); then
        echo "!! Cannot reach the database for '$slug'. Stopping." >&2
        exit 1
    fi
    head=$(run_as_reticle --env "$env_file" "$ALEMBIC" heads 2>/dev/null | tail -1)

    if [[ "$DRY_RUN" == true ]]; then
        printf '    %-20s at %-40s target %s\n' "$slug" "${current:-<none>}" "$head"
        continue
    fi

    echo "--> $slug"

    # Back up before migrating, every time. This is what makes the migration
    # reversible, and it runs while the old code is still serving.
    "$SCRIPT_DIR/backup-facility.sh" "$slug" pre-migrate

    if ! run_as_reticle --env "$env_file" "$ALEMBIC" upgrade head; then
        cat >&2 <<STOPPED

!! Migration failed for '$slug'. Stopped here deliberately.

   Facilities before this one are migrated; this one and everything after it
   are not. Do NOT switch the release symlink — the old code is still correct
   for the un-migrated facilities, and the migrated ones can read it because
   migrations here are additive.

   Its backups: ${dir%/}/backups/pre-migrate-*.dump   (pg_restore)
                ${dir%/}/backups/pre-migrate-*.tar.gz (media, portable corpus)
   Its logs:    journalctl -u reticle@$slug

STOPPED
        exit 1
    fi
done

[[ "$DRY_RUN" == true ]] && exit 0

echo "==> All ${#FACILITIES[@]} migrated. Backups are in each facility's backups/."

#!/bin/sh
# Upgrade a Reticle installation in place.
#
#   deploy/upgrade.sh            # pull the images named by RETICLE_VERSION in .env
#   deploy/upgrade.sh --build    # build from this checkout instead (after `git pull`)
#
# Order matters and is the whole point of having a script:
#   1. back up — a release may migrate the database, and a migration cannot be
#      undone by starting the old image;
#   2. fetch (or build) the new images while the old ones still serve;
#   3. migrate, if this release changes the database schema: the API is
#      stopped, and the new image migrates with this script's word that the
#      backup exists (RETICLE_ALLOW_MIGRATE=1). Started any other way, a
#      release that needs a migration refuses to run and changes nothing;
#   4. swap. The proxy is replaced only once the new API is healthy.
#
# Rolling back is in docs/DEPLOYMENT.md, "Rolling back". This script prints
# exactly what you need for it.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

build=false
for argument in "$@"; do
    case "$argument" in
    --build) build=true ;;
    *) die "unknown option $argument" ;;
    esac
done

previous_app="$(compose ps --format '{{.Image}}' app 2>/dev/null | head -n 1 || true)"
previous_web="$(compose ps --format '{{.Image}}' web 2>/dev/null | head -n 1 || true)"

# An API container that is not serving — typically one that was started on
# the new release without this script, refused to migrate, and is now being
# restarted by Docker every minute — is stopped first. Left alone it would
# notice the backup below and begin the migration by itself, at the same
# moment as step 3.
app_is_healthy || compose stop app >/dev/null 2>&1 || true

echo "== 1/4  Backup"
"$(dirname -- "$0")/backup.sh"

echo "== 2/4  New images"
if [ "$build" = true ]; then
    compose build --pull app web
else
    compose pull app web
fi

echo "== 3/4  Database schema"
# Read-only, and asked of the NEW image while the old one still serves.
state="$(compose run --rm --no-deps -T app reticle-entrypoint schema-state </dev/null)" ||
    die "could not ask the new image about the database; nothing was changed and the old release is still running"
echo "$state"
case "$state" in
pending\ *)
    echo "This release changes the database schema. Stopping the API and migrating..."
    compose stop app
    if ! compose run --rm --no-deps -T -e RETICLE_ALLOW_MIGRATE=1 app reticle-entrypoint migrate </dev/null; then
        echo >&2
        echo "The migration failed; the reason is above. The API is stopped." >&2
        echo "To go back: put the previous RETICLE_VERSION in .env and run 'docker compose up -d'." >&2
        echo "If that release then says the database is from a newer release, the migration" >&2
        echo "got part of the way: restore the backup taken a minute ago with deploy/restore.sh." >&2
        echo "  app was  ${previous_app:-unknown}" >&2
        exit 1
    fi
    ;;
newer\ *)
    die "the database was written by a NEWER release than the images just fetched; nothing was changed. Check RETICLE_VERSION in .env"
    ;;
*)
    echo "No schema change in this release."
    ;;
esac

echo "== 4/4  Restart on the new images"
if [ "$build" = true ]; then
    compose up -d --wait --no-build
else
    compose up -d --wait --no-build --pull never
fi

compose ps
echo
echo "Upgrade complete. Version requested in .env: $(setting RETICLE_VERSION '(not set)')"
echo "The images that were running before, should you need to go back:"
echo "  app  ${previous_app:-unknown}"
echo "  web  ${previous_web:-unknown}"
echo "and the backup taken a minute ago is the newest file in $(setting RETICLE_BACKUP_DIR "$RETICLE_HOME/backups")."

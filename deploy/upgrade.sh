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
#   3. swap. The new application container migrates the schema before it
#      accepts a request; the proxy is replaced only once the API is healthy.
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

echo "== 1/3  Backup"
"$(dirname -- "$0")/backup.sh"

echo "== 2/3  New images"
if [ "$build" = true ]; then
    compose build --pull app web
else
    compose pull app web
fi

echo "== 3/3  Restart on the new images"
if [ "$build" = true ]; then
    compose up -d --wait --no-build
else
    compose up -d --wait --no-build --pull never
fi

compose ps
echo
echo "Upgrade complete. Version requested in .env: $(setting RETICLE_VERSION latest)"
echo "The images that were running before, should you need to go back:"
echo "  app  ${previous_app:-unknown}"
echo "  web  ${previous_web:-unknown}"
echo "and the backup taken a minute ago is the newest file in $(setting RETICLE_BACKUP_DIR "$RETICLE_HOME/backups")."

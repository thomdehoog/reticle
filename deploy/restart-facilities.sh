#!/usr/bin/env bash
#
# Restart every facility on this host and wait for each one to answer.
#
#     ./restart-facilities.sh
#
# One release directory serves every facility, so moving the `current` symlink
# changes the code under all of them at once and each process has to be
# restarted to pick it up. This is what the deploy runs after the symlink moves,
# and — the reason it is a script rather than eight lines of YAML — it is also
# what the deploy runs to roll back. A rollback that restarts nothing leaves
# every facility running the release that just failed, with a symlink that says
# otherwise.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

set -euo pipefail

# shellcheck source=deploy/reticle-lib.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/reticle-lib.sh"

ATTEMPTS="${RETICLE_READY_ATTEMPTS:-30}"
INTERVAL="${RETICLE_READY_INTERVAL:-2}"

mapfile -t SLUGS < <(reticle_facility_slugs)
if [[ ${#SLUGS[@]} -eq 0 ]]; then
    echo "No facilities under $RETICLE_ROOT/facilities. Run provision-facility.sh first." >&2
    exit 1
fi

for slug in "${SLUGS[@]}"; do
    env_file="$(reticle_env_file "$slug")"

    # The port is in the facility's own env file, which only `reticle` can
    # read — so it is asked for on that side of the sudo. Reading it directly
    # gives an empty string and a poll against http://127.0.0.1:/api/ready,
    # which fails every time and looks exactly like a broken release.
    port="$(run_as_reticle --env "$env_file" printenv RETICLE_PORT)"
    if [[ -z "$port" ]]; then
        echo "!! $slug has no RETICLE_PORT in $env_file. Stopping." >&2
        exit 1
    fi

    sudo systemctl restart "reticle@$slug"

    # Readiness, not liveness. The process answers /api/health before it can
    # reach the database, so waiting on that would call a release good while it
    # is still broken.
    ready=false
    for _ in $(seq 1 "$ATTEMPTS"); do
        if curl -sf "http://127.0.0.1:$port/api/ready" >/dev/null; then
            ready=true
            break
        fi
        sleep "$INTERVAL"
    done

    if [[ "$ready" != true ]]; then
        echo "!! $slug never became ready on port $port." >&2
        echo "   journalctl -u reticle@$slug -n 100 --no-pager" >&2
        exit 1
    fi
    echo "    $slug ready on $port"
done

echo "==> ${#SLUGS[@]} facilities restarted and answering."

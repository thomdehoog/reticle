# Shared by the scripts in this directory; sourced, not executed.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

# The directory that holds compose.yaml and .env — one above this file.
RETICLE_HOME="${RETICLE_HOME:-$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)}"

die() {
    echo "$(basename -- "$0"): $*" >&2
    exit 1
}

compose() {
    # RETICLE_COMPOSE lets a host with a differently named binary
    # (docker-compose, podman compose) use these scripts unchanged.
    # shellcheck disable=SC2086  # deliberately split into words
    (cd "$RETICLE_HOME" && ${RETICLE_COMPOSE:-docker compose} "$@")
}

# Read one setting from .env without executing the file. The environment wins,
# as it does for Compose itself.
setting() {
    name="$1"
    fallback="$2"
    value="$(printenv "$name" || true)"
    if [ -z "$value" ] && [ -f "$RETICLE_HOME/.env" ]; then
        value="$(sed -n "s/^[[:space:]]*$name=//p" "$RETICLE_HOME/.env" | tail -n 1 |
            sed -e 's/[[:space:]]*$//' -e "s/^'\(.*\)'\$/\1/" -e 's/^"\(.*\)"$/\1/')"
    fi
    printf '%s\n' "${value:-$fallback}"
}

app_is_running() {
    [ -n "$(compose ps --status running --quiet app 2>/dev/null)" ]
}

# Running AND answering its health check. A container that Docker is
# restarting over and over (one that refuses to start, say) is "running" for a
# second at a time; a command sent into it dies with it.
app_is_healthy() {
    [ "$(compose ps --format '{{.Health}}' app 2>/dev/null | head -n 1)" = "healthy" ]
}

# Run a command in the application image with the data volume attached: inside
# the serving container when there is one, in a throwaway one when there is
# not (so a backup can still be taken from a stack that will not start).
in_app() {
    if app_is_healthy; then
        compose exec -T app "$@"
    else
        compose run --rm --no-deps -T app "$@"
    fi
}

[ -f "$RETICLE_HOME/compose.yaml" ] || die "no compose.yaml in $RETICLE_HOME"

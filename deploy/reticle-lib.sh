# shellcheck shell=bash
#
# Shared by every script in this directory. Not executable and not run on its
# own — `source` it.
#
# It exists for one reason: these scripts migrate production databases, and the
# prelude that switches to the `reticle` account and loads a facility's
# environment has to be identical everywhere it appears. Written out by hand at
# each call site it drifts, and a wrong shell flag in one copy is wrong
# silently. There is one copy, here.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

# Where everything lives. Overridable so the scripts can be exercised against a
# scratch directory without a server.
RETICLE_ROOT="${RETICLE_ROOT:-/opt/reticle}"

# The account that owns the data. Not the account that receives the deploy —
# see deploy/reticle-deploy.sudoers for why those are two different people.
RETICLE_SERVICE_USER="${RETICLE_SERVICE_USER:-reticle}"

# The release directory is a symlink that moves. Resolving it at each use rather
# than once at start means a long-running loop keeps talking to the release it
# started with, which is what we want mid-deploy.
reticle_backend_dir() { printf '%s\n' "$RETICLE_ROOT/current/backend"; }
reticle_venv_bin()    { printf '%s\n' "$RETICLE_ROOT/current/venv/bin"; }

reticle_facility_dir() { printf '%s\n' "$RETICLE_ROOT/facilities/$1"; }
reticle_env_file()     { printf '%s\n' "$RETICLE_ROOT/facilities/$1/env"; }

# Every facility on this host, one slug per line. The directory names are the
# register — a facility exists because its directory does, so nothing has to be
# kept in step with a list somewhere else.
reticle_facility_slugs() {
    local dir
    shopt -s nullglob
    for dir in "$RETICLE_ROOT"/facilities/*/; do
        basename "$dir"
    done
}

# Run a command as the service account.
#
#     run_as_reticle --env /opt/reticle/facilities/zmb/env alembic upgrade head
#     run_as_reticle test -f /opt/reticle/facilities/zmb/env
#
# With --env, the facility's environment file is loaded and the working
# directory is the backend — that is the form alembic, app.seed and
# app.portability need. Without it, the command simply runs as `reticle`.
#
# The plain form is not a convenience. A facility directory is 0750 and owned by
# `reticle`, so the account that receives the deploy cannot stat a file inside
# one. Checking "does this facility have an env file" therefore has to happen on
# the other side of the sudo, or every facility looks broken.
#
# Everything goes through `bash -c`, including the plain form, because one
# `bash` line is the whole of what /etc/sudoers.d/reticle-deploy grants. One
# rule is one thing to audit.
#
# The flags, once, with the reason for each:
#
#   set -e         a failure inside the inner shell has to reach the caller.
#                  Without it the `cd` could fail and alembic would run in the
#                  wrong directory against the wrong alembic.ini.
#   set -o pipefail  the caller pipes this into `tail`. Without pipefail the
#                  pipeline reports tail's status, so an unreachable database
#                  reads as success with empty output — and `--dry-run` prints
#                  "<none>", which means "never migrated" rather than "cannot
#                  reach this database".
#   umask 077      anything these commands write is a database dump or a corpus
#                  archive — every guide, every photograph, every password hash
#                  in the facility. The default umask would make those readable
#                  by anyone with an account on the machine.
#   set -a         every variable the env file defines has to be *exported*,
#                  because alembic and the application read the environment,
#                  not this shell's variables. `set +a` straight after so the
#                  command's own assignments are not exported too.
#
# The env file path, the directory and the command are passed as real arguments
# rather than pasted into a string, so a path containing a space or a quote
# cannot turn into shell syntax.
run_as_reticle() {
    local env_file=""
    if [[ "${1:-}" == "--env" ]]; then
        env_file="$2"
        shift 2
    fi
    sudo -u "$RETICLE_SERVICE_USER" bash -c '
        set -eo pipefail
        umask 077
        if [[ -n "$1" ]]; then
            set -a
            # shellcheck disable=SC1090  # the file is chosen by the caller
            . "$1"
            set +a
            cd "$2"
        fi
        shift 2
        exec "$@"
    ' reticle-run "$env_file" "$(reticle_backend_dir)" "$@"
}

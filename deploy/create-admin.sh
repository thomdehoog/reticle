#!/bin/sh
# Create the first administrator (and the eight ZMB categories) on a new
# installation.
#
#   deploy/create-admin.sh           # asks for an email address and a password
#   deploy/create-admin.sh --demo    # also loads demonstration content
#
# The password is typed here and handed to the container on standard input, so
# it is never written to .env, to the shell history or to a process listing.
# Safe to run again: an account that already exists is left alone, password
# included — this is not a password reset (see docs/MAINTENANCE.md for that).
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

demo=""
for argument in "$@"; do
    case "$argument" in
    --demo) demo="--demo" ;;
    *) die "unknown option $argument" ;;
    esac
done

app_is_running || die "the stack is not running; start it with 'docker compose up -d' first"
[ -t 0 ] || die "this script asks questions; run it from a terminal"

printf 'Administrator email: '
read -r email
[ -n "$email" ] || die "an email address is required"

trap 'stty echo 2>/dev/null || true' EXIT INT TERM
stty -echo
printf 'Password (at least 12 characters): '
read -r password
printf '\nAgain: '
read -r again
stty echo
printf '\n'
[ "$password" = "$again" ] || die "the two passwords differ; nothing was created"
[ "${#password}" -ge 12 ] || die "the password must be at least 12 characters long"

# shellcheck disable=SC2016  # the $ signs are for the shell inside the container
printf '%s\n%s\n' "$email" "$password" | compose exec -T app sh -c '
    IFS= read -r RETICLE_ADMIN_EMAIL
    IFS= read -r RETICLE_ADMIN_PASSWORD
    export RETICLE_ADMIN_EMAIL RETICLE_ADMIN_PASSWORD
    exec reticle-entrypoint seed "$@"' seed $demo

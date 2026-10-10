#!/bin/sh
# Break-glass: set a new password for an account from the server's console.
#
#   deploy/reset-password.sh
#
# For the day the last administrator has forgotten theirs. In every other case
# an administrator does this in the browser, under People. The account is
# reactivated if it was deactivated, and all of its sessions are ended.
#
# Whoever can run this can become any user — which is to say, whoever has
# root on this host already could. It leaves a line in the container log, not
# in Reticle's audit trail.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
set -eu

# shellcheck source-path=SCRIPTDIR source=lib.sh
. "$(dirname -- "$0")/lib.sh"

app_is_running || die "the stack is not running; start it with 'docker compose up -d' first"
[ -t 0 ] || die "this script asks questions; run it from a terminal"

printf 'Email address of the account: '
read -r email
[ -n "$email" ] || die "an email address is required"

trap 'stty echo 2>/dev/null || true' EXIT INT TERM
stty -echo
printf 'New password (at least 12 characters): '
read -r password
printf '\nAgain: '
read -r again
stty echo
printf '\n'
[ "$password" = "$again" ] || die "the two passwords differ; nothing was changed"
[ "${#password}" -ge 12 ] || die "the password must be at least 12 characters long"

printf '%s\n%s\n' "$email" "$password" | compose exec -T app python -c '
import sys

from sqlalchemy import select

from app import db
from app.models import User
from app.security import end_credentials, hash_password

email = sys.stdin.readline().strip().lower()
password = sys.stdin.readline().rstrip("\n")
with db.SessionLocal() as session:
    user = session.scalars(select(User).where(User.email == email)).one_or_none()
    if user is None:
        sys.exit(f"There is no account {email}; nothing was changed.")
    user.password_hash = hash_password(password)
    user.is_active = True
    role = user.role
    # Ends its sessions and raises its epoch, so device cookies issued under
    # the old password stop verifying too.
    end_credentials(session, user)
    session.commit()
print(f"Password set for {email} ({role}); its sessions were ended.", flush=True)
'

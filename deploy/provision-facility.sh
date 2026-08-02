#!/usr/bin/env bash
#
# Add a facility: database, media directory, environment, service, vhost.
#
#     sudo ./provision-facility.sh zmb "Center for Microscopy and Image Analysis" admin@zmb.uzh.ch
#
# What this does NOT do, deliberately: install the software. The software is
# already there — one release directory, one virtualenv, shared by every
# facility. A facility is a database, a media directory, an environment file
# and a subdomain. Adding one copies no code.
#
# If any step fails, everything this run created is undone before it exits — see
# the `undo` function. Without that, a run that stops halfway leaves behind a
# database role whose password exists nowhere but the terminal scrollback, and a
# directory whose presence makes the next attempt refuse to start.
#
# Optional environment:
#   RETICLE_DOMAIN        default reticle.ch
#   RETICLE_ROOT          default /opt/reticle
#   RETICLE_DB_HOST       default localhost
#   RETICLE_DB_ADMIN      default postgres
#   RETICLE_BASE_PORT     default 8000
#   RETICLE_MEDIA_ORIGIN  empty unless this facility serves media from object
#                         storage — see step 6.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/reticle-lib.sh
. "$SCRIPT_DIR/reticle-lib.sh"

SLUG="${1:-}"
NAME="${2:-}"
ADMIN_EMAIL="${3:-}"
DOMAIN="${RETICLE_DOMAIN:-reticle.ch}"
DB_HOST="${RETICLE_DB_HOST:-localhost}"
DB_ADMIN="${RETICLE_DB_ADMIN:-postgres}"
MEDIA_ORIGIN="${RETICLE_MEDIA_ORIGIN:-}"

NGINX_SNIPPET_DIR="${RETICLE_NGINX_SNIPPET_DIR:-/etc/nginx/snippets}"
NGINX_SITES_DIR="${RETICLE_NGINX_SITES_DIR:-/etc/nginx/sites-available}"
NGINX_ENABLED_DIR="${RETICLE_NGINX_ENABLED_DIR:-/etc/nginx/sites-enabled}"

if [[ -z "$SLUG" || -z "$NAME" || -z "$ADMIN_EMAIL" ]]; then
    echo "usage: $0 <slug> <display name> <admin email>" >&2
    echo "   eg: $0 zmb 'Center for Microscopy and Image Analysis' admin@zmb.uzh.ch" >&2
    exit 64
fi

# The slug becomes a subdomain, a database name, a systemd instance and a
# directory. Validating it once here is cheaper than discovering which of those
# four rejects a space.
if [[ ! "$SLUG" =~ ^[a-z][a-z0-9-]{1,30}$ ]]; then
    echo "Refusing '$SLUG': use lower-case letters, digits and hyphens, starting with a letter." >&2
    exit 64
fi

FACILITY_DIR="$(reticle_facility_dir "$SLUG")"
ENV_FILE="$(reticle_env_file "$SLUG")"
SNIPPET_FILE="$NGINX_SNIPPET_DIR/reticle-$SLUG-headers.conf"
VHOST_FILE="$NGINX_SITES_DIR/reticle-$SLUG"
VHOST_LINK="$NGINX_ENABLED_DIR/reticle-$SLUG"

DB_NAME="reticle_${SLUG//-/_}"
DB_USER="reticle_${SLUG//-/_}"

if [[ -e "$FACILITY_DIR" ]]; then
    echo "Refusing: $FACILITY_DIR already exists. Remove it deliberately if you mean to start over." >&2
    exit 65
fi

# --- what to undo if this run does not finish ------------------------------
# Each flag is set the moment the thing it names exists, so the cleanup below
# removes exactly what this run created and nothing else. That is the whole
# safety argument: the checks further down refuse to start if the role or the
# database is already there, so anything the cleanup drops was made here.
CREATED_ROLE=false
CREATED_DATABASE=false
CREATED_DIR=false
CREATED_SNIPPET=false
CREATED_VHOST=false
ENABLED_SERVICE=false
SUCCEEDED=false

psql_admin() { sudo -u "$DB_ADMIN" psql -v ON_ERROR_STOP=1 "$@"; }

undo() {
    local status=$?
    trap - EXIT

    if [[ "$SUCCEEDED" == true ]]; then
        exit "$status"
    fi

    # Nothing was created yet — a refusal from one of the checks above. Saying
    # "undoing what this run created" there would suggest something happened.
    local made="$CREATED_ROLE$CREATED_DATABASE$CREATED_DIR$CREATED_SNIPPET$CREATED_VHOST$ENABLED_SERVICE"
    if [[ "$made" != *true* ]]; then
        exit "$status"
    fi

    echo "" >&2
    echo "!! Provisioning '$SLUG' failed. Undoing what this run created." >&2

    # Every step tolerates its own failure. A cleanup that stops halfway is
    # worse than no cleanup, because it leaves a state nobody has a name for.
    if [[ "$ENABLED_SERVICE" == true ]]; then
        echo "   - stopping reticle@$SLUG" >&2
        systemctl disable --now "reticle@$SLUG" >/dev/null 2>&1 || true
    fi

    if [[ "$CREATED_VHOST" == true ]]; then
        echo "   - removing the vhost" >&2
        rm -f "$VHOST_LINK" "$VHOST_FILE" || true
        # Only reload once the remaining configuration is known to parse. A
        # reload against a broken file takes down every other facility on the
        # host, which would turn one failed provisioning into an outage.
        if nginx -t >/dev/null 2>&1; then
            systemctl reload nginx >/dev/null 2>&1 || true
        fi
    fi

    if [[ "$CREATED_SNIPPET" == true ]]; then
        rm -f "$SNIPPET_FILE" || true
    fi

    # The database goes before the role, because the role owns it. FORCE
    # disconnects anything still attached — the service may have opened a
    # connection a second ago.
    if [[ "$CREATED_DATABASE" == true ]]; then
        echo "   - dropping database $DB_NAME" >&2
        psql_admin -c "DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE)" >/dev/null 2>&1 \
            || echo "     could not drop $DB_NAME; drop it by hand" >&2
    fi

    if [[ "$CREATED_ROLE" == true ]]; then
        echo "   - dropping role $DB_USER" >&2
        psql_admin -c "DROP ROLE IF EXISTS $DB_USER" >/dev/null 2>&1 \
            || echo "     could not drop $DB_USER; drop it by hand" >&2
    fi

    if [[ "$CREATED_DIR" == true && -n "$FACILITY_DIR" ]]; then
        echo "   - removing $FACILITY_DIR" >&2
        rm -rf "${FACILITY_DIR:?}" || true
    fi

    echo "   Nothing of this facility is left. Fix the cause and run it again." >&2
    exit "$status"
}
trap undo EXIT

# --- 0. refuse before creating anything ------------------------------------
# Reaching the database now, rather than at the first CREATE, means an
# unreachable server is a clear message instead of a half-made facility.
if ! psql_admin -tAc 'SELECT 1' >/dev/null 2>&1; then
    echo "Cannot reach PostgreSQL as '$DB_ADMIN'. Is it running, and is this being run with sudo?" >&2
    exit 69
fi

existing_role="$(psql_admin -tAc "SELECT 1 FROM pg_roles WHERE rolname = '$DB_USER'")"
existing_db="$(psql_admin -tAc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'")"

if [[ -n "$existing_role" || -n "$existing_db" ]]; then
    cat >&2 <<ALREADY
Refusing: PostgreSQL already has ${existing_role:+role $DB_USER}${existing_role:+${existing_db:+ and }}${existing_db:+database $DB_NAME}.

This script only removes what it created, so it will not touch either of those.
If they are left over from a previous attempt, remove them deliberately:

    sudo -u $DB_ADMIN psql -c 'DROP DATABASE IF EXISTS $DB_NAME WITH (FORCE)'
    sudo -u $DB_ADMIN psql -c 'DROP ROLE IF EXISTS $DB_USER'

If they belong to a facility that is actually in use, you want a different slug.
ALREADY
    exit 65
fi

# Ports are derived from a base so two facilities cannot collide, and recorded
# in the environment file so nothing has to recompute it later.
# Taken from the env files rather than from what is listening: a facility that
# is merely stopped still owns its port, and handing it to a new facility means
# the older one fails the next time it starts.
BASE_PORT="${RETICLE_BASE_PORT:-8000}"
PORT=$BASE_PORT
while grep -rqs "^RETICLE_PORT='\?$PORT'\?$" "$RETICLE_ROOT"/facilities/*/env \
   || ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; do
    PORT=$((PORT + 1))
done

echo "==> Facility '$SLUG' at ${SLUG}.${DOMAIN} on port $PORT"

# --- 1. the database -------------------------------------------------------
# One per facility. This is the isolation decision: a query that forgets its
# filter cannot reach another facility's data, because the connection does not
# contain it.
DB_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"

echo "==> Creating role $DB_USER"
psql_admin <<SQL
CREATE ROLE $DB_USER LOGIN PASSWORD '$DB_PASSWORD';
SQL
CREATED_ROLE=true

echo "==> Creating database $DB_NAME"
psql_admin <<SQL
CREATE DATABASE $DB_NAME OWNER $DB_USER ENCODING 'UTF8';
SQL
CREATED_DATABASE=true

# No rights on anything else. The role can reach its own database and nothing
# more, which is the second half of the isolation the separate database buys.
psql_admin -d "$DB_NAME" <<SQL
REVOKE ALL ON DATABASE $DB_NAME FROM PUBLIC;
SQL

# --- 2. the directories ----------------------------------------------------
install -d -o "$RETICLE_SERVICE_USER" -g "$RETICLE_SERVICE_USER" -m 750 "$FACILITY_DIR"
CREATED_DIR=true
install -d -o "$RETICLE_SERVICE_USER" -g "$RETICLE_SERVICE_USER" -m 750 "$FACILITY_DIR/media"
# Backups are 0700, not 0750: a dump holds every password hash in the facility.
install -d -o "$RETICLE_SERVICE_USER" -g "$RETICLE_SERVICE_USER" -m 700 "$FACILITY_DIR/backups"

# --- 3. the environment ----------------------------------------------------
# The secret key is per facility on purpose. It is the pepper for session-token
# digests, so sharing one would mean a stolen database from one facility could
# be used to forge sessions at another.
SECRET_KEY="$(openssl rand -base64 48 | tr -d '\n')"

# A single quote inside a single-quoted shell value ends the quoting. Replacing
# each one with '\'' closes, escapes and reopens - the standard idiom, and the
# reason a name like "St John's Imaging" does not break the file.
SAFE_NAME=${NAME//\'/\'\\\'\'}
SAFE_EMAIL=${ADMIN_EMAIL//\'/\'\\\'\'}
ADMIN_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"

(umask 077; cat > "$ENV_FILE" <<ENV
# Generated by provision-facility.sh for $SLUG. Facility-specific settings only;
# anything shared belongs in the code, not here.
# Every value is single-quoted. This file is read by systemd AND sourced by
# bash during provisioning, and an unquoted value containing a space makes bash
# read the rest of the line as a command - so a plain multi-word facility name
# silently produced an empty variable, and a value containing a command
# substitution would have been executed.
RETICLE_SECRET_KEY='$SECRET_KEY'
RETICLE_DATABASE_URL='postgresql+psycopg://$DB_USER:$DB_PASSWORD@$DB_HOST/$DB_NAME'
RETICLE_MEDIA_ROOT='$FACILITY_DIR/media'
RETICLE_PORT='$PORT'

RETICLE_ORGANISATION_NAME='$SAFE_NAME'
RETICLE_ORGANISATION_SHORT_NAME='${SLUG^^}'
RETICLE_ORGANISATION_URL='https://${SLUG}.${DOMAIN}'

RETICLE_COOKIE_SECURE=true
RETICLE_LOG_LEVEL=INFO

# Media on local disk, under RETICLE_MEDIA_ROOT above. Switching a facility to
# object storage means setting RETICLE_STORAGE_BACKEND='s3' with the
# RETICLE_S3_* settings, AND naming the storage origin in this facility's
# Content-Security-Policy - otherwise every image is blocked. See DEPLOYMENT.md,
# "Object storage".
RETICLE_STORAGE_BACKEND='local'

# Leave this off. uvicorn is started with --proxy-headers
# --forwarded-allow-ips 127.0.0.1 (see reticle@.service), so it has already
# replaced the peer address with the real client's before any request reaches
# the application, and attribution in the audit log and the login throttle is
# correct as it stands.
#
# Turning it on is actively worse here. It switches the application to reading
# the leftmost entry of X-Forwarded-For, which is the entry a client controls
# the moment anyone changes nginx to append rather than overwrite - and a
# value that is not an address at all becomes "no address", which drops the
# per-(account, address) login limit to the far looser per-account one and
# turns the per-address limit off entirely.
RETICLE_TRUST_FORWARDED_FOR=false

# Same-origin in production: nginx serves the pages and /api under one
# hostname, so CORS never comes into play.
RETICLE_CORS_ORIGINS='https://${SLUG}.${DOMAIN}'

RETICLE_ADMIN_EMAIL='$SAFE_EMAIL'
RETICLE_ADMIN_PASSWORD='$ADMIN_PASSWORD'
ENV
)
chown "$RETICLE_SERVICE_USER:$RETICLE_SERVICE_USER" "$ENV_FILE"

# --- 4. schema and first account ------------------------------------------
echo "==> Migrating"
run_as_reticle --env "$ENV_FILE" "$(reticle_venv_bin)/alembic" upgrade head

echo "==> Seeding the first administrator"
run_as_reticle --env "$ENV_FILE" "$(reticle_venv_bin)/python" -m app.seed

# The bootstrap password exists to be used once and replaced. Removing it from
# the environment file means it is not sitting on disk after first sign-in, and
# `app.seed` is idempotent so its absence changes nothing on later runs.
sed -i '/^RETICLE_ADMIN_PASSWORD=/d' "$ENV_FILE"

# --- 5. the service --------------------------------------------------------
echo "==> Starting reticle@$SLUG"
systemctl enable --now "reticle@$SLUG"
ENABLED_SERVICE=true

ready=false
for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$PORT/api/ready" >/dev/null; then
        ready=true
        break
    fi
    sleep 2
done
if [[ "$ready" != true ]]; then
    echo "The service started but never became ready. Check: journalctl -u reticle@$SLUG" >&2
    exit 70
fi

# --- 6. the vhost and its security headers ---------------------------------
# The headers are a separate file included from every block of the vhost.
# nginx's add_header does not inherit into a block that defines one of its own,
# and the block that answers with index.html defines a Cache-Control - so a
# single copy at the top of the server would reach everything except the page
# that runs JavaScript. Read the top of nginx-security-headers.conf.template.
#
# {{MEDIA_ORIGIN}} is empty for local-disk media. With RETICLE_STORAGE_BACKEND
# set to s3 the application answers a media request with a redirect to a signed
# URL on the storage provider, and the browser judges that URL against this
# policy, so the provider's origin has to be named:
#
#     RETICLE_MEDIA_ORIGIN=https://s3.eu-central-1.amazonaws.com \
#         sudo ./provision-facility.sh …
install -d -m 755 "$NGINX_SNIPPET_DIR"
sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{DOMAIN}}|$DOMAIN|g" -e "s|{{MEDIA_ORIGIN}}|$MEDIA_ORIGIN|g" \
    "$SCRIPT_DIR/nginx-security-headers.conf.template" > "$SNIPPET_FILE"
CREATED_SNIPPET=true

sed -e "s|{{SLUG}}|$SLUG|g" -e "s|{{DOMAIN}}|$DOMAIN|g" -e "s|{{PORT}}|$PORT|g" \
    -e "s|{{HEADERS}}|$SNIPPET_FILE|g" \
    "$SCRIPT_DIR/nginx-facility.conf.template" > "$VHOST_FILE"
ln -sfn "$VHOST_FILE" "$VHOST_LINK"
CREATED_VHOST=true

# `nginx -t && systemctl reload nginx` looks like it fails loudly and does not.
# `set -e` ignores a failure on the left-hand side of an AND list, so a vhost
# that does not parse leaves nginx un-reloaded while this script goes on to
# announce that the facility is up.
if ! nginx -t; then
    echo "The generated vhost does not parse. Nothing has been reloaded." >&2
    exit 71
fi
systemctl reload nginx

SUCCEEDED=true

cat <<DONE

    Facility '$SLUG' is up.

      URL        https://${SLUG}.${DOMAIN}
      Admin      $ADMIN_EMAIL
      Password   $ADMIN_PASSWORD

    Give that password to the administrator by a route that is not email, and
    tell them to change it at first sign-in. It has already been removed from
    the environment file, so this is the only place it appears.

    Still to do by hand:
      - DNS: point ${SLUG}.${DOMAIN} at this host (or use a wildcard record).
      - TLS: certbot --nginx -d ${SLUG}.${DOMAIN}, unless a wildcard
        certificate for *.${DOMAIN} is already installed.

DONE

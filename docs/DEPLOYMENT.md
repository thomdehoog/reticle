# Deploying Reticle

This guide is written to be understood, not just pasted. If you know why each
piece is there, you can fix it at 4pm on a Friday when something is wrong.

The supported way to run Reticle is **Docker Compose on one Linux host**
(sections 1–13). Running it directly on a VM with nginx and systemd still
works and is described in section 14, but it is the secondary path: you
assemble by hand what the images already contain.

## 1. What the moving parts are

Two containers and a disk:

```
        browsers on the ZMB / UZH network
                    │  :443 (and :80, which only redirects)
                    ▼
        ┌───────────────────────┐
        │  web   (Caddy)        │   terminates HTTPS
        │                       │   serves the built frontend
        │                       │   forwards /api/* to the API
        └───────────┬───────────┘
                    │  http://app:8000 on a private network with no way out
                    ▼
        ┌───────────────────────┐
        │  app   (uvicorn +     │   the API, auth, permissions,
        │         FastAPI)      │   PDF export, media
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │  volume reticle-data  │
        │   /data/reticle.db    │   guides, pages, users, history
        │   /data/media/        │   uploaded images and videos
        │   /data/tmp, caches   │   scratch space; nothing to keep
        └───────────────────────┘
```

**The frontend is static files.** It is built once, into the `web` image.
There is no Node process in production; Caddy hands out HTML, CSS and
JavaScript, which is why the site stays fast on an ordinary VM.

**The API never serves the frontend, and Caddy never serves the media.** Caddy
answers everything except `/api/*`; the API answers only `/api/*`. Uploaded
images and videos live on the API's volume, which the `web` container cannot
even see, and reach a browser only through `/api/media/{id}` — where every
request is checked against the login and against what that person may read.
If you ever find yourself pointing a web server at the media directory "to
make it faster", stop: that would publish every draft's photographs.

**Same origin, so no CORS.** Pages and API share one hostname, so the browser
is making same-origin requests and `RETICLE_CORS_ORIGINS` is empty in this
deployment. That setting exists for development, where the frontend is on port
5173 and the API on 8000.

**The database is a file.** SQLite, in write-ahead (WAL) mode: `reticle.db`
plus two companions, `reticle.db-wal` and `reticle.db-shm`, which are part of
the database and must stay next to it. For one institute's editing load this
is the right answer — no separate service, no separate thing to break.
Section 15 covers when that stops being true.

**The API container starts in two steps.** First the database schema is
brought to what this release expects (`python -m app.migrate`); then uvicorn
starts. The server itself refuses to run against a schema it does not
recognise.

**A migration needs a way back.** A new installation is migrated without
ceremony, and a start that has nothing to migrate is never held up. But when a
new release would *change* an existing database, the container does that only
if a backup was taken within the last hour — which is what `deploy/upgrade.sh`
does — and otherwise stops with a message and leaves the database exactly as
it was. The old image cannot read a migrated database, so this is the one step
of an upgrade that cannot be undone by putting the old version number back
(section 7).

## 2. What you need before starting

- **A Linux host** — a VM is fine. 2 vCPU, 2 GB RAM and 20 GB of disk is a
  comfortable start (section 10 has the reasoning). The disk must be local:
  SQLite's locking is not reliable on NFS or SMB shares.
- **Docker Engine 25 or newer with the Compose plugin** (`docker compose
  version` should print v2.24 or later). The `docker.io` package of Debian 12
  is too old; install from Docker's own repository
  (<https://docs.docker.com/engine/install/>). Ubuntu 24.04's is new enough.
- **A DNS name** pointing at the host, e.g. `reticle.zmb.uzh.ch`. Ask UZH IT.
- **A decision about the certificate** — section 4. At UZH this usually means
  asking IT for one at the same time as the DNS name.
- **Ports 80 and 443** reachable from wherever staff will read guides.

**HTTPS is not optional.** The session cookie is issued with the `Secure` flag,
which means browsers refuse to send it over plain http. Without TLS, nobody can
log in. This is a feature — it is the difference between a password crossing
the university network encrypted and in the clear.

## 3. First install

### 3.1 Get the files

A server needs four things: `compose.yaml`, `.env`, the `deploy/` scripts, and
the two images. Either:

**From a release** (recommended — nothing is built on the server). Download
`reticle-deploy-<version>.tar.gz` from the repository's Releases page:

```bash
sudo mkdir -p /opt/reticle && sudo chown "$USER" /opt/reticle
tar -xzf reticle-deploy-1.2.0.tar.gz --strip-components=1 -C /opt/reticle
cd /opt/reticle
```

**Or from a git checkout** (you build the images yourself; needs a few minutes
and about 1 GB of free disk during the build):

```bash
sudo mkdir -p /opt/reticle && sudo chown "$USER" /opt/reticle
git clone https://github.com/thomdehoog/reticle /opt/reticle
cd /opt/reticle
```

The rest of this guide assumes `/opt/reticle`. Nothing depends on that path
except the systemd units for backups and housekeeping, which say so.

### 3.2 Write the configuration

```bash
cp .env.example .env
chmod 600 .env
openssl rand -base64 48      # paste the output into RETICLE_SECRET_KEY
nano .env
```

`.env.example` documents every setting. The ones you must set:

```ini
RETICLE_DOMAIN=reticle.zmb.uzh.ch
RETICLE_SECRET_KEY=<the value you just generated>
RETICLE_VERSION=1.2.0           # already filled in by a release bundle
RETICLE_TLS_MODE=files          # or auto — see section 4
```

`RETICLE_SECRET_KEY` is the pepper for session-token hashes. Compose refuses
to start without it, without `RETICLE_DOMAIN` and without `RETICLE_VERSION`,
with a message that says which one is missing. A shipped default secret would
be the same on every installation, which is exactly what a secret must not be.
Changing it later logs everyone out, which is occasionally exactly what you
want (section 12).

`chmod 600` because this file is the key to every session.

**`RETICLE_VERSION` is always a number, never `latest`.** There is no default
on purpose: which release a server runs should be written down, so that "what
are we running?" has an answer, an upgrade is a decision, and nothing changes
because somebody typed `docker compose pull`.

- A release bundle has it filled in with the release the bundle came from.
- The list of releases, with notes, is
  <https://github.com/thomdehoog/reticle/releases>; the version is the tag
  without the `v`.
- In a git checkout, set `RETICLE_VERSION=dev`: you build what you checked
  out, and the images are named `…:dev`.
- `docker compose images` shows what a host is running right now.

### 3.3 Choose how HTTPS is provided

Read section 4 and set `RETICLE_TLS_MODE`. If the certificate comes from
university IT, put the two files in `deploy/certs/` now.

### 3.4 Start it

From a release:

```bash
docker compose pull
docker compose up -d --no-build
```

From a git checkout:

```bash
docker compose up -d --build
```

Then:

```bash
docker compose ps
```

Both services should say `healthy` within half a minute. `app` is healthy
when its API answers and the database responds; `web` is healthy when Caddy
runs *and* can reach the API. If one of them keeps restarting,
`docker compose logs web` (or `app`) says why in its last lines —
`MAINTENANCE.md` section 9 lists the usual suspects.

### 3.5 Create the first administrator

```bash
deploy/create-admin.sh
```

It asks for an email address and a password (at least 12 characters) and
creates that administrator plus the eight ZMB categories. The password is
handed to the container on standard input, so it never lands in `.env`, in
the shell history or in a process listing. Reticle refuses to invent a
default password, because a default admin password is how internal tools get
owned.

It is safe to run again; an existing account is never touched. (If you would
rather script it: set `RETICLE_ADMIN_EMAIL` and `RETICLE_ADMIN_PASSWORD` in
`.env`, run `docker compose up -d` so the container sees them, run
`docker compose exec app reticle-entrypoint seed`, and then delete the
password line again.)

### 3.6 Check it actually works

```bash
curl -sf https://reticle.zmb.uzh.ch/api/health            # {"status":"ok"}
curl -si https://reticle.zmb.uzh.ch/api/guides | head -1  # 401 — correct
```

That 401 is the single most important check on this page. It proves the site
is behind the login. If it ever returns 200, stop and investigate.

Then open the site, sign in, create a test guide, upload an image, publish it,
and read it on your phone.

### 3.7 Turn on backups — today, not later

```bash
deploy/backup.sh
```

then schedule it: `MAINTENANCE.md` section 2. An installation without a
scheduled backup is a draft. While you are there, schedule the weekly
housekeeping as well (`MAINTENANCE.md` section 7), so that the media
directory does not only ever grow.

## 4. HTTPS: the three modes (and "off")

`RETICLE_TLS_MODE` in `.env` selects one of four small files in
`deploy/caddy/modes/`. Everything else about the site is identical between
them.

### `files` — a certificate from university IT

**Probably the one you want at UZH.** A host that is only reachable inside
the university network cannot use Let's Encrypt (see `auto` below), and IT
issues certificates for `uzh.ch` names.

1. Create a key and a signing request, and send the `.csr` (never the key) to
   IT:

   ```bash
   cd /opt/reticle/deploy/certs
   openssl req -new -newkey rsa:2048 -nodes \
     -keyout privkey.pem -out reticle.csr \
     -subj "/CN=reticle.zmb.uzh.ch" \
     -addext "subjectAltName=DNS:reticle.zmb.uzh.ch"
   ```

2. Save what comes back as `fullchain.pem`. It must contain **the whole
   chain**: your certificate first, then the intermediate(s), concatenated.
   If IT sends them as separate files:
   `cat reticle.crt intermediate.crt > fullchain.pem`. A missing intermediate
   is the classic failure: desktop browsers often cope, phones and `curl` do
   not.

3. Make the key readable by Caddy, which runs as uid 10002 and not as root:

   ```bash
   sudo chown 10002 privkey.pem fullchain.pem
   sudo chmod 400 privkey.pem
   ```

4. In `.env`: `RETICLE_TLS_MODE=files`. Different file names or another
   directory: `RETICLE_TLS_CERT_FILE`, `RETICLE_TLS_KEY_FILE`,
   `RETICLE_TLS_CERT_DIR`.

**Renewal is on you.** Certificates expire, and an expired certificate takes
the whole site down because the session cookie is `Secure`. Put the expiry
date in a calendar *with a month's notice*:

```bash
openssl x509 -enddate -noout -in deploy/certs/fullchain.pem
```

Caddy reads the files once, at start. After replacing them:

```bash
docker compose restart web
```

### `auto` — Let's Encrypt, obtained and renewed automatically

Zero maintenance, **if** the certificate authority can reach you:
`RETICLE_DOMAIN` must resolve in *public* DNS to this host, and port 80 or 443
must be reachable *from the internet*, because Let's Encrypt connects back to
prove you control the name. From inside a firewalled university network that
check cannot succeed, and Caddy will log failed challenges every few minutes
while the site answers with a certificate error. If that is what you see, use
`files`.

Certificates and the ACME account live in the `caddy-data` volume. Keep it
across upgrades (it is); Let's Encrypt rate-limits re-issuing for the same
name to a handful per week.

### `internal` — Caddy's own private certificate authority

Real HTTPS, signed by an authority only this Caddy knows. Every browser warns
until the root certificate is installed on that machine:

```bash
docker compose exec web cat /data/caddy/pki/authorities/local/root.crt
```

Useful for a test rig where you want `Secure` cookies and HSTS to behave as in
production. Not for staff.

### `off` — plain HTTP

For exactly two situations:

- **A trial on your own machine.** `RETICLE_DOMAIN=localhost`,
  `RETICLE_TLS_MODE=off`, `RETICLE_COOKIE_SECURE=false`,
  `RETICLE_HTTP_PORT=8080`, and browse to <http://localhost:8080>. The README
  has this as a five-minute quickstart. `RETICLE_COOKIE_SECURE=false` is what
  makes sign-in work over http, and it is the reason this configuration must
  never face a network: the password and the session travel in the clear.
- **Behind another reverse proxy that terminates TLS** — section 5.
  `RETICLE_COOKIE_SECURE` stays `true` there.

In the three HTTPS modes, port 80 answers only with a redirect to
`https://<domain>/…`, and every response carries
`Strict-Transport-Security`. The redirect assumes HTTPS is on port 443.

### What Caddy adds to every page

Set in `deploy/caddy/Caddyfile`, and worth knowing about before you change the
frontend:

- **A Content-Security-Policy** that allows the frontend its own scripts and
  stylesheets and nothing else: no inline script, no `<style>` elements, no
  third-party hosts, images and video only from this origin (plus `data:` and
  `blob:` for local previews), `fetch` only to this origin, no framing. React's
  `style={{…}}` props keep working — they are applied through the DOM, which a
  CSP does not restrict. **Consequence:** an image hot-linked from another
  website in a wiki page will not load. That is intended — a guide should not
  break because someone else's server moved, nor tell that server who is
  reading — so upload the image instead. CI drives a real browser through the
  site under this policy and fails on any violation, so a frontend change
  that needs a wider policy is caught before it ships.
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: same-origin`, a `Permissions-Policy` that switches off
  camera, microphone, geolocation and friends.
- **Caching**: files under `/assets/` have a content hash in their name and
  are cached for a year; `index.html` (which every client-side route such as
  `/g/…`, `/w/…`, `/c/…`, `/t/…` falls back to) is revalidated on every load,
  so a deployment reaches people on their next click.
- **Body limits**: 2 MB everywhere, except `POST /api/media`, which may carry
  one video of up to `RETICLE_MAX_VIDEO_BYTES` (200 MB). There is no time
  limit on an upload, on purpose: 200 MB over a slow uplink takes minutes.
- **Compression** (zstd or gzip) for text: the frontend's files and the API's
  JSON. Images, video and PDF are compressed formats already and pass through
  byte for byte.
- API responses pass through with the headers the application sets itself:
  its stricter security headers, and for media its own caching rule. Caddy
  adds no `Cache-Control` to `/api/` and caches nothing.

**How media is cached, and why.** An image or video is answered with
`Cache-Control: private, no-cache` and an `ETag`. In words: the reader's own
browser may keep the file, shared caches may not, and the browser asks before
every reuse — a question the API answers with a short "not modified" when
nothing changed, after checking the login and the permissions again. That is
what makes a photograph disappear from someone's screen once the guide it
belonged to is unpublished or the upload is deleted, instead of lingering for
an hour. `Range`, `If-None-Match` and `If-Range` request headers reach the API
untouched, which is what lets a video seek. To see it for yourself (the cookie
jar comes from a sign-in with `curl -c`):

```bash
curl -s -b jar.txt -o /dev/null -D - https://reticle.zmb.uzh.ch/api/media/<id> \
  | grep -i -E '^(HTTP|cache-control|etag|content-encoding)'
```

## 5. Behind an existing reverse proxy

If UZH IT runs a central reverse proxy or load balancer that holds the
certificate and forwards to your host, Reticle's Caddy stays in the picture —
it still serves the frontend and guards the API — but speaks plain HTTP to
that proxy:

```ini
RETICLE_TLS_MODE=off
RETICLE_COOKIE_SECURE=true            # the browser's connection IS https
RETICLE_HTTP_PORT=8080                # whatever the proxy forwards to
RETICLE_UPSTREAM_PROXIES=...          # see "Which address to put there" below
```

**`RETICLE_UPSTREAM_PROXIES` is the setting that matters.** Reticle throttles
logins per client address and writes that address into its audit log. With a
proxy in front, every connection comes *from the proxy*, and the real client
is only known from the `X-Forwarded-For` header the proxy adds — a header any
browser can also send. So the rule is: believe that header from the proxy,
and from nobody else.

- Leave it **empty** when browsers connect to this host directly. Then nobody's
  header is believed.
- Set it **without** such a proxy, or too broadly, and any client can pick its
  own address: a fresh login-throttle bucket for every guess, or a colleague's
  address in the audit log.
- **Forget** it behind a proxy and nothing is insecure, but everyone shares
  one address: twenty mistyped passwords anywhere in the building throttle
  sign-in for the whole institute.

How the chain works, so you can check it: Caddy works out the client address
(the connection's own address, or — only for connections from
`RETICLE_UPSTREAM_PROXIES` — the right-most address in `X-Forwarded-For` that
is not itself one of those proxies), **overwrites** `X-Forwarded-For` with
exactly that one address, and passes the request on. The API believes the
header only from Caddy's private network (`RETICLE_TRUSTED_PROXIES`, which
`compose.yaml` sets to that network's fixed subnet for you). uvicorn runs with
`--no-proxy-headers`, so there is no second, independent opinion.

### Which address to put there

Not the proxy's name, and not necessarily the address you would use to reach
it: the address its connections **arrive from**, as seen by Reticle's Caddy
inside its container. Docker sits in between, and what it does to the source
address depends on where the proxy is.

| Where the proxy runs | What it connects to | Caddy sees it as | Set |
| --- | --- | --- | --- |
| **Another machine** | this host's address, port `RETICLE_HTTP_PORT` | the proxy's own address — Docker forwards the connection without rewriting where it came from | `RETICLE_UPSTREAM_PROXIES=10.20.30.40` (every node, or the CIDR block, if it is a cluster) |
| **This machine**, as an ordinary service (nginx, Apache, HAProxy, another Caddy) | `127.0.0.1:8080` | **`172.31.251.1`**, not `127.0.0.1`: a connection to a published port on localhost is carried into the container by Docker itself and arrives from the gateway of Reticle's `edge` network | `RETICLE_UPSTREAM_PROXIES=172.31.251.1` and `RETICLE_BIND_ADDRESS=127.0.0.1` |
| **This machine**, in a container of its own (not part of Reticle's Compose project) | this host's address, port 8080 | `172.31.251.1` as well: Docker carries traffic between two of its networks the same way | `RETICLE_UPSTREAM_PROXIES=172.31.251.1`; the port then has to listen on that host address, so close it to everyone else in the firewall (section 6) and read the IPv6 note there |

`172.31.251.1` is the first address of `RETICLE_EDGE_SUBNET`
(`172.31.251.0/24` unless you changed it — if you did, it is the first address
of your range, and
`docker network inspect reticle_edge --format '{{(index .IPAM.Config 0).Gateway}}'`
prints it). Name that one address, not the subnet.

**For a proxy on this machine, `RETICLE_BIND_ADDRESS=127.0.0.1` is part of
the setting, not an extra.** `172.31.251.1` does not mean "the proxy"; it
means "anything that reached the published port through Docker's own
forwarding" — which is every program on this host and, with Docker's default
networking, also every IPv6 visitor (section 6). Trusting that address while
the port is open to the network would let those visitors choose the address
Reticle records for them. Bound to `127.0.0.1`, the port can only be reached
from this machine, and what remains trusted is: local processes. On a
dedicated VM that is the proxy and you.

Two cases that look similar and are not:

- A proxy on this machine that connects to the host's **own network address**
  (`192.0.2.10:8080` rather than `127.0.0.1:8080`) arrives with that network
  address as its source. Point it at `127.0.0.1` instead; it is the
  arrangement the table describes, and it lets you close the port to
  everybody else.
- **Rootless Docker and Podman** forward ports differently, and every
  connection may arrive from one internal address whatever its origin. Do not
  guess; use the check below, and if `remote_ip` is the same for a request
  through the proxy and a request made directly, a same-host proxy cannot be
  told apart from the rest — bind to `127.0.0.1` so that there is no "rest".

### Check what Reticle actually saw

Do this after any change in front of Reticle. It takes a minute and it is the
only way to know.

1. From a machine whose address you know, through the proxy, make one request
   that leaves a trace — a sign-in that fails on purpose:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -H 'Content-Type: application/json' \
     -d '{"email":"address-check@example.org","password":"wrong-on-purpose"}' \
     https://reticle.zmb.uzh.ch/api/auth/login          # 401
   ```

2. What **Caddy** saw — `remote_ip` is where the connection came from,
   `client_ip` is the address Caddy decided the client has:

   ```bash
   docker compose logs --tail 20 web | grep /api/auth/login \
     | grep -o -E '"(remote_ip|client_ip)": "[^"]*"' | tail -n 2
   ```

3. What **the application** recorded, which is what the login throttle and
   the audit trail use:

   ```bash
   docker compose exec app python -c "
   import sqlite3
   db = sqlite3.connect('file:/data/reticle.db?mode=ro', uri=True)
   for row in db.execute('SELECT created_at, action, ip_address FROM audit_log ORDER BY created_at DESC LIMIT 3'):
       print(*row)"
   ```

Reading the result:

| `remote_ip` | `client_ip` and the audit log | Meaning |
| --- | --- | --- |
| the proxy (per the table above) | **your machine's address** | Correct. |
| the proxy | the proxy again | `RETICLE_UPSTREAM_PROXIES` is missing, or does not contain what `remote_ip` shows. `remote_ip` *is* the value to put there — once you are sure it is your proxy and nothing else. |
| the proxy | an address that is neither yours nor the proxy's | The proxy does not set `X-Forwarded-For` itself but passes on (or appends to) what the client sent. Ask its operators to set the header from the connection. |
| your machine's address | your machine's address | Your request did not go through the proxy at all: the port is reachable directly. Close it (firewall, or `RETICLE_BIND_ADDRESS`). |

Then repeat step 1 with a forged header, `-H 'X-Forwarded-For: 203.0.113.99'`.
The audit log must still show your real address. If it shows `203.0.113.99`,
something between you and Reticle believes clients: either the proxy passes
the header through, or `RETICLE_UPSTREAM_PROXIES` trusts an address your
request arrived from directly.

### What to ask of whoever runs the proxy

- forward the original `Host` header, and **set** `X-Forwarded-For` to the
  address of the connection (not pass on what the client sent);
- connect over IPv4;
- allow request bodies of 210 MB on `/api/media` and do not buffer them to
  disk first; allow that request several minutes;
- do not cache `/api/`, and pass `Range`, `If-Range` and `If-None-Match`
  request headers and `ETag` / `Cache-Control` response headers through
  untouched — that is what lets a video seek and what keeps a deleted image
  from being served out of somebody's cache;
- add `Strict-Transport-Security` (in `off` mode Reticle's pages do not).

## 6. Firewall and ports

| Port | Who needs it | Why |
| --- | --- | --- |
| 443/tcp | everyone who reads guides | the site |
| 80/tcp | the same | redirects to https; Let's Encrypt in `auto` mode |
| 443/udp | optional | HTTP/3; browsers fall back to TCP without it |
| 22/tcp | administrators | you |

Nothing else is published. The API's port 8000 exists only on a private
Docker network, which is also marked `internal`: the API container cannot open
a connection to anything outside, so a bug in it cannot be used to reach other
university systems or to send data out.

**Docker publishes ports around `ufw`.** Docker writes its own firewall rules,
and they are consulted before ufw's, so `ufw deny 443` does *not* close a port
that a container publishes. Restrict access in the network firewall in front
of the host, with rules in Docker's `DOCKER-USER` chain, or by setting
`RETICLE_BIND_ADDRESS` to one specific address of the host.

**IPv6.** Docker's default networks are IPv4. If the host has an IPv6 address
and the DNS name has an AAAA record, IPv6 visitors reach Caddy through
Docker's userland proxy and all appear to come from one internal address
(`172.31.251.1`, the gateway of the `edge` network) — the shared-throttle
problem from section 5. Either do not publish an AAAA record, or enable IPv6
in Docker (<https://docs.docker.com/engine/daemon/ipv6/>) and check with the
commands in section 5, "Check what Reticle actually saw". Do **not** solve it
by putting `172.31.251.1` into `RETICLE_UPSTREAM_PROXIES` on a host whose
ports are open to the network: that would let every one of those visitors
choose their own address.

## 7. Upgrading

```bash
cd /opt/reticle
nano .env                 # RETICLE_VERSION=1.3.0   (release installs)
deploy/upgrade.sh         # git checkouts: git pull, then deploy/upgrade.sh --build
```

**Always through `deploy/upgrade.sh`.** The script does four things in an
order that matters:

1. **Backs up.** A release may migrate the database, and a migration cannot
   be undone by starting the old image.
2. **Fetches (or builds) the new images** while the old ones still serve.
3. **Migrates, if this release changes the database schema.** It asks the new
   image (read-only, while the old one is still serving), prints the answer,
   and only if there is something to migrate stops the API and runs the
   migration.
4. **Swaps.** `web` is replaced once the new API is healthy. Expect a few
   seconds during which the site does not answer.

At the end it prints the images that were running before and where the backup
is — the two things a rollback needs.

Read the release notes first. A release is a bundle — `compose.yaml`,
`.env.example`, `deploy/` and these two documents — and the pieces belong
together: **unpack the new bundle over the installation** before running the
new `deploy/upgrade.sh`, and compare `.env.example` with your `.env` for new
settings. Your `.env`, your certificates and anything in a
`compose.override.yaml` are never part of a release and are never overwritten.

```bash
tar -xzf reticle-deploy-1.3.0.tar.gz --strip-components=1 -C /opt/reticle
```

### What happens if you skip the script

`docker compose pull && docker compose up -d` is how most Compose projects are
upgraded, so somebody will do it. With a release that does **not** change the
schema, that works. With one that does, the new `app` container stops before
touching anything and says so in `docker compose logs app`:

```
reticle: NOT STARTED, and nothing has been changed.

This release has to migrate the database (schema revision 0003 -> 0004). A
migration cannot be undone by going back to the previous image, so it is not
run without a fresh backup — and there is none on record (...).

  To upgrade:     deploy/upgrade.sh
  To stay put:    set RETICLE_VERSION in .env back to the release you were
                  running, then: docker compose up -d
```

The site is down at that point (the old containers were replaced), Docker
restarts the new one every minute, and each time it declines again. Both ways
out are safe, and both are in the message: run `deploy/upgrade.sh`, or put the
old version back — the database is exactly as the old release left it.

What counts as "a fresh backup": `deploy/backup.sh`, once the archive has been
written **and read back**, leaves a note on the data volume; the new release
migrates if that note is less than an hour old
(`RETICLE_MIGRATE_BACKUP_MAX_AGE_MINUTES`) and describes the database as it is
now. So by hand, the upgrade is:

```bash
deploy/backup.sh
docker compose pull                       # or: docker compose build --pull
docker compose up -d --no-build
docker compose ps
```

There is also an override, for the day you know better than the safeguard:
`RETICLE_ALLOW_MIGRATE=1 docker compose up -d` migrates without asking for a
backup. It is what `upgrade.sh` itself uses for step 3, after its own backup.
Use it on a command line; never write it into `.env`, where it would quietly
switch the safeguard off for every upgrade to come.

None of this is ever in the way of an ordinary start: a new installation is
migrated without questions, and a restart, a reboot or a
`docker compose up -d` after editing `.env` has nothing to migrate.

Images are rebuilt only when a release is tagged, so the operating-system
packages inside them are as old as the release. Upgrading Reticle a few times
a year is also how those get patched.

## 8. Rolling back

Put the old version back and start it:

```bash
nano .env                                 # RETICLE_VERSION=1.2.0
docker compose pull && docker compose up -d --no-build
```

(From a git checkout: `git checkout v1.2.0 && docker compose up -d --build`.)

If the newer release did **not** change the database schema, that is all, and
everything written since the upgrade is still there — which is what you want,
since guides written since then are real work.

If it **did** — `upgrade.sh` said so in its step 3, "This release changes the
database schema" — the old `app` container refuses to start, and
`docker compose logs app` ends with an explanation: the database was already
migrated and the older release cannot read it. Then, and only then, also
restore the backup that `upgrade.sh` took:

```bash
ls -t backups/ | head                     # the one from just before the upgrade
deploy/restore.sh backups/reticle-<stamp>.tar.gz
```

Content written between the upgrade and the rollback is lost in that case.
That is the honest cost of rolling back across a migration, and the reason to
watch a new release for an hour rather than a week before deciding.

## 9. Moving to another host

Everything that makes an installation *this* installation is three things: a
backup archive, `.env`, and (in `files` mode) `deploy/certs/`.

```bash
# old host
deploy/backup.sh
scp backups/reticle-<stamp>.tar.gz .env newhost:/tmp/
scp -r deploy/certs newhost:/tmp/certs          # files mode only

# new host: section 3.1, then
cp /tmp/.env /opt/reticle/.env && chmod 600 /opt/reticle/.env
sudo cp -a /tmp/certs/. /opt/reticle/deploy/certs/   # then chown 10002 as in section 4
cd /opt/reticle
docker compose pull && docker compose up -d --no-build
deploy/restore.sh /tmp/reticle-<stamp>.tar.gz
```

Then point the DNS name at the new host. Because `.env` came along, the secret
key is the same and people stay signed in. In `auto` mode the new host obtains
its own certificate the moment the name points at it.

Stop the old host's stack (`docker compose down`) once the name has moved, so
nobody keeps editing a copy that is about to be thrown away.

## 10. Sizing

Reticle is small. What actually consumes resources:

- **Memory.** Each sign-in costs 64 MiB for a fraction of a second (Argon2id,
  deliberately expensive). Re-encoding a 40-megapixel photograph takes a few
  hundred MiB while it lasts. A video upload costs almost nothing: it is
  streamed to disk. The `app` container is capped at 1 GiB
  (`RETICLE_APP_MEMORY`) and `web` at 256 MiB, so a 2 GB host has room for the
  operating system as well. If large stitched images are routine, give the
  host 4 GB and raise the cap to `2g`.
- **CPU.** Two API workers by default (`RETICLE_WORKERS`), so the site keeps
  answering while one is rendering a PDF. Two cores are plenty.
- **Disk.** The database stays in the tens of megabytes. Media is what grows:
  a photograph is 0.2–3 MB, a video up to 200 MB. Next to each photograph the
  server keeps a *display copy* of bounded dimensions, which is what a
  reader's browser is sent, so a 40-megapixel original is not downloaded to
  a phone; it is smaller than the original and is made again if it is ever
  missing. Rendered PDFs are cached too, one per published version of a
  guide.
  `RETICLE_MAX_MEDIA_STORE_BYTES` puts a ceiling on the media directory if
  you want uploads to stop before the disk does, and the weekly housekeeping
  job (`MAINTENANCE.md` section 7) removes what nothing refers to any more.
  **Backups multiply it** —
  every archive is a full copy, and `RETICLE_BACKUP_KEEP_DAYS` (default 14) of
  them are kept. With 5 GB of media that is 70 GB of local backups. Either
  size for it, lower the retention and let the off-machine backup system keep
  the history, or point `RETICLE_BACKUP_DIR` at separate storage.
  `MAINTENANCE.md` section 7 shows how to see where the space went.
- **Temporary space.** An upload in progress is spooled to `/data/tmp` on the
  data volume — on disk, not in a RAM-backed `/tmp`, so a 200 MB video costs
  no memory. The volume therefore needs one video's worth of free space per
  simultaneous upload on top of what is stored.

## 11. Where things are

| Thing | Where |
| --- | --- |
| Compose file, scripts | `/opt/reticle/compose.yaml`, `/opt/reticle/deploy/` |
| Configuration | `/opt/reticle/.env` |
| Certificates (`files` mode) | `/opt/reticle/deploy/certs/` |
| Database | volume `reticle_reticle-data`, `/data/reticle.db` (+ `-wal`, `-shm`) |
| Uploaded images and videos, and the display copies made from them | same volume, `/data/media/` |
| Scratch space: uploads in transit, cached PDFs | same volume, `/data/tmp/` and `/data/media/.pdf-cache/`; never backed up, safe to lose |
| Caddy's certificates (`auto`, `internal`) | volume `reticle_caddy-data` |
| Backups | `/opt/reticle/backups/` unless `RETICLE_BACKUP_DIR` says otherwise |
| Logs | `docker compose logs app`, `docker compose logs web` |
| Proxy configuration | inside the `web` image; source in `deploy/caddy/` |

The volumes are directories under `/var/lib/docker/volumes/`. Look, but do not
copy the database out of there while the stack runs — `deploy/backup.sh`
exists because that copy can be silently corrupt.

**Changing the proxy configuration.** The Caddyfile is part of the `web`
image. To change it without rebuilding, copy `deploy/caddy/` from the
repository, edit, and mount it from a `compose.override.yaml`:

```yaml
services:
  web:
    volumes:
      - ./deploy/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - ./deploy/caddy/modes:/etc/caddy/modes:ro
```

## 12. Rotating the secret

If `RETICLE_SECRET_KEY` is ever exposed — pasted into a ticket, committed by
accident, on a stolen laptop — generate a new one, put it in `.env`, and:

```bash
docker compose up -d
```

Every session becomes invalid and everyone signs in again. Passwords are
unaffected; they are hashed with Argon2id independently of this key.

## 13. What the containers are allowed to do

Not much, on purpose. If you loosen any of this, know what it was for.

| Measure | Where | Why |
| --- | --- | --- |
| Unprivileged users (uid 10001, 10002) | both images | a compromised process is nobody in particular |
| `read_only: true` | `compose.yaml` | nothing can be planted in the image's filesystem; the only writable places are the data volume and a small RAM `/tmp` |
| `cap_drop: ALL`, `no-new-privileges` | `compose.yaml` | no Linux capabilities, and no way to gain any through a setuid binary |
| `internal: true` on the API's network | `compose.yaml` | the API cannot make outbound connections at all |
| Fixed subnet for that network | `compose.yaml` | "requests from the proxy" is something `RETICLE_TRUSTED_PROXIES` can state exactly (change `RETICLE_SUBNET` only if 172.31.250.0/24 collides with something) |
| Fixed subnet for the outward network too | `compose.yaml` | a reverse proxy on the same host arrives from that network's gateway, 172.31.251.1, and section 5 has to be able to name it (`RETICLE_EDGE_SUBNET`) |
| No migration of an existing database without a fresh backup | image entrypoint | the one step of an upgrade that cannot be undone by going back (section 7) |
| Python packages installed by hash | `backend/requirements.lock` | the image contains exactly the files that were tested, or the build fails |
| Memory and process limits | `compose.yaml` | a runaway upload takes down a container, which restarts, not the host |
| Log rotation (5 × 10 MB per service) | `compose.yaml` | logs cannot fill the disk |
| `restart: unless-stopped` | `compose.yaml` | back after a crash and after a reboot — provided Docker itself starts at boot (`sudo systemctl enable docker`) |

Caddy listens on ports 80 and 443 *inside* its container as an unprivileged
user; that is what the `net.ipv4.ip_unprivileged_port_start` line in
`compose.yaml` is for.

The one-off `tools` service (used by the content import, `docs/IMPORT.md`) is
the deliberate exception to "no outbound connections": it has the data volume
*and* a route out, runs only when you invoke it with
`docker compose run --rm tools …`, and exits when the command does.

## 14. Without Docker: nginx and systemd on a VM

The secondary path. Everything above about *why* still applies; this section
is the same machine assembled by hand. Choose it only if Docker is not an
option on the host.

### 14.1 Account, layout, code

Reticle runs as its own unprivileged user.

```bash
sudo apt update && sudo apt install -y python3-venv nginx git fonts-dejavu-core sqlite3
sudo adduser --system --group --home /opt/reticle reticle
sudo -u reticle mkdir -p /opt/reticle/{releases,shared/media,static}
sudo -u reticle git clone https://github.com/thomdehoog/reticle /opt/reticle/releases/first
cd /opt/reticle/releases/first
sudo -u reticle python3 -m venv venv
sudo -u reticle venv/bin/pip install --require-hashes -r backend/requirements.lock
sudo -u reticle ln -sfn /opt/reticle/releases/first /opt/reticle/current
```

Python 3.13, the version the lock file was resolved for and the one the image
runs. (`requirements.lock` pins every package to exact versions and file
hashes. On Python 3.12 the same command normally works as well; if pip
complains that a package has no matching file, install from
`backend/requirements.txt` instead and accept that the versions are then
whatever is newest within its ranges.) `fonts-dejavu-core` is for the PDF export: without it,
λ, Å and ≥ print as boxes. `shared/` holds what must survive a deployment —
database, media, configuration. Deployments swap the `current` symlink.

### 14.2 Configuration

```bash
sudo -u reticle cp backend/.env.example /opt/reticle/shared/reticle.env
sudo chmod 600 /opt/reticle/shared/reticle.env
sudo -u reticle nano /opt/reticle/shared/reticle.env
```

```ini
RETICLE_SECRET_KEY=<openssl rand -base64 48>
RETICLE_DATABASE_URL=sqlite:////opt/reticle/shared/reticle.db
RETICLE_MEDIA_ROOT=/opt/reticle/shared/media
RETICLE_COOKIE_SECURE=true
RETICLE_TRUSTED_PROXIES=127.0.0.1
RETICLE_CORS_ORIGINS=
```

Note the **four** slashes in the SQLite URL — `sqlite:////opt/...` is an
absolute path; three would be relative to the working directory and you would
get a second, empty database the first time systemd started you elsewhere.

`RETICLE_TRUSTED_PROXIES=127.0.0.1` names nginx, which runs on the same host.
It replaces the old `RETICLE_TRUST_FORWARDED_FOR` switch, which no longer
exists: the server refuses to start if that is set on its own, because "trust
the header from anybody" was wrong in both positions. Delete the line if you
are carrying an old file forward.

### 14.3 Schema, first administrator

```bash
cd /opt/reticle/current/backend
sudo -u reticle env RETICLE_ENV_FILE=/opt/reticle/shared/reticle.env \
     ../venv/bin/python -m app.migrate
sudo -u reticle env RETICLE_ENV_FILE=/opt/reticle/shared/reticle.env \
     RETICLE_ADMIN_EMAIL=you@zmb.uzh.ch RETICLE_ADMIN_PASSWORD='<a long passphrase>' \
     ../venv/bin/python -m app.seed
```

`app.migrate` creates the schema on an empty database and upgrades an
existing one; it is safe on every deploy. **The server will not start until it
has been run** — it checks the schema and refuses, with an instruction, rather
than failing one request at a time on a missing column.

### 14.4 The API under systemd

`/etc/systemd/system/reticle.service`:

```ini
[Unit]
Description=Reticle guide platform
After=network.target

[Service]
Type=exec
User=reticle
Group=reticle
WorkingDirectory=/opt/reticle/current/backend
Environment=RETICLE_ENV_FILE=/opt/reticle/shared/reticle.env
Environment=TMPDIR=/opt/reticle/shared/tmp
ExecStartPre=/usr/bin/mkdir -p /opt/reticle/shared/tmp
ExecStartPre=/opt/reticle/current/venv/bin/python -m app.migrate
ExecStart=/opt/reticle/current/venv/bin/python -m uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 2 --no-proxy-headers
Restart=always
RestartSec=3

# The service needs to write exactly one directory. Everything else is read-only.
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
NoNewPrivileges=true
ReadWritePaths=/opt/reticle/shared

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now reticle
sudo systemctl status reticle
```

- **`ExecStartPre=… app.migrate`** makes every restart migrate first, so an
  update is "switch the symlink, restart". Unlike the container, nothing here
  checks that a backup exists before a migration runs — on this path that is
  your job, and the first line of section 14.7.
- **`--no-proxy-headers`** matters. By default uvicorn rewrites the client
  address from `X-Forwarded-For` itself, for connections from 127.0.0.1 —
  a second copy of the trust decision, made before Reticle sees the request.
  With the flag, `RETICLE_TRUSTED_PROXIES` is the only thing deciding.
- **`TMPDIR`** is where a video upload is spooled before it is copied into the
  media root. With `PrivateTmp`, the default `/tmp` may be a small RAM disk;
  pointing it at the data disk means a 200 MB upload costs disk, not memory.
- **Bind to `127.0.0.1`**, never `0.0.0.0` — the API must be reachable only
  through nginx.
- **`Restart=always`** is the part people skip. A bare `uvicorn` in a terminal
  dies with the terminal.

### 14.5 The frontend

Build it on a workstation or in CI — the server does not need Node:

```bash
cd frontend && npm ci && npx vite build
rsync -av --delete dist/ reticle@<host>:/opt/reticle/static/
```

### 14.6 nginx

`/etc/nginx/sites-available/reticle`:

```nginx
server {
    listen 80;
    server_name reticle.zmb.uzh.ch;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;      # nginx 1.25.1+: "listen 443 ssl;" and "http2 on;"
    server_name reticle.zmb.uzh.ch;

    ssl_certificate     /etc/ssl/reticle/fullchain.pem;
    ssl_certificate_key /etc/ssl/reticle/privkey.pem;

    # Everything fits in 2 MB — except uploads, below.
    client_max_body_size 2m;

    root /opt/reticle/static;
    index index.html;

    # The one request that may be large: a video of up to 200 MB plus
    # multipart framing. Streamed to the API, not buffered by nginx first,
    # and given time: a slow uplink needs minutes.
    location = /api/media {
        client_max_body_size 210m;
        proxy_request_buffering off;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        include /etc/nginx/snippets/reticle-proxy.conf;
    }

    location /api/ {
        # Not buffered: a video is fetched in Range requests while it plays.
        proxy_buffering off;
        include /etc/nginx/snippets/reticle-proxy.conf;
    }

    # Hashed file names: cache for a year. A missing asset is a 404, never the
    # app shell under a JavaScript URL.
    location /assets/ {
        include /etc/nginx/snippets/reticle-headers.conf;
        add_header Cache-Control "public, max-age=31536000, immutable" always;
        try_files $uri =404;
    }

    # Reticle is a single-page app: the server has no /c/light-microscopy file,
    # so unmatched paths fall back to index.html — which must not be cached,
    # or a deployment never reaches anyone.
    location / {
        include /etc/nginx/snippets/reticle-headers.conf;
        add_header Cache-Control "no-cache" always;
        try_files $uri /index.html;
    }
}
```

`/etc/nginx/snippets/reticle-headers.conf` — for the pages only. The API sets
its own, stricter headers, which is why these are included in the two static
locations and not at server level, where the `/api/` responses would inherit
them and carry everything twice:

```nginx
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options DENY always;
add_header Referrer-Policy same-origin always;
add_header Strict-Transport-Security "max-age=31536000" always;
add_header Content-Security-Policy "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" always;
```

`/etc/nginx/snippets/reticle-proxy.conf`:

```nginx
proxy_pass http://127.0.0.1:8000;
proxy_http_version 1.1;
proxy_set_header Host              $host;
# Overwrite, not append ($proxy_add_x_forwarded_for would keep whatever the
# client sent). Reticle reads the header from the right and would cope, but
# one address is the one with no room for a mistake.
proxy_set_header X-Forwarded-For   $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
```

The media directory appears nowhere in this file, and must not: media is
served by the API only, per request, behind the login. nginx passes `Range`
headers through by default; do not add `proxy_cache` to `/api/`.

```bash
sudo ln -s /etc/nginx/sites-available/reticle /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

For the certificate, the same choice as section 4: files from IT in
`/etc/ssl/reticle/`, or certbot (`sudo apt install certbot
python3-certbot-nginx && sudo certbot --nginx -d reticle.zmb.uzh.ch`) if the
host is reachable from the internet.

Then the checks of section 3.6.

### 14.7 Updating, rolling back, backing up

```bash
sudo /usr/local/bin/reticle-backup        # below; always first
NEW=/opt/reticle/releases/$(date +%Y%m%d-%H%M)
sudo -u reticle git clone --depth 1 --branch v1.3.0 https://github.com/thomdehoog/reticle $NEW
cd $NEW && sudo -u reticle python3 -m venv venv
sudo -u reticle venv/bin/pip install --require-hashes -r backend/requirements.lock
sudo -u reticle ln -sfn $NEW /opt/reticle/current
sudo systemctl restart reticle            # migrates, then starts
curl -sf https://reticle.zmb.uzh.ch/api/health
```

plus a rebuilt frontend rsynced to `/opt/reticle/static/`. To roll back, point
`current` at the previous release and restart; if the service then refuses to
start because the schema is newer than the code, restore the backup taken
before the update (stop the service, replace `reticle.db`, **delete
`reticle.db-wal` and `reticle.db-shm`**, replace `media/`, start).

`deploy/backup.sh` is for the Compose deployment. On a bare VM,
`/usr/local/bin/reticle-backup`:

```bash
#!/bin/bash
set -euo pipefail
umask 077
BACKUP_DIR=/var/backups/reticle
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$BACKUP_DIR"

# .backup goes through SQLite and is safe on a live WAL database; cp is not.
sqlite3 /opt/reticle/shared/reticle.db ".backup '$WORK/reticle.db'"

# tar exits 1 when a file changed or vanished while it was being read — which
# is what a video being uploaded at this moment looks like, and not a reason
# to have no backup tonight: the database copy above does not refer to that
# file yet. Anything above 1 is a real error. Scratch directories stay out.
STATUS=0
tar -czf "$BACKUP_DIR/reticle-$STAMP.tar.gz.partial" \
    --exclude='tmp' --exclude='.tmp' --exclude='cache' --exclude='.pdf-cache' --exclude='*.part' \
    -C "$WORK" reticle.db -C /opt/reticle/shared media || STATUS=$?
if [ "$STATUS" -gt 1 ]; then
    rm -f "$BACKUP_DIR/reticle-$STAMP.tar.gz.partial"
    echo "backup FAILED (tar exit $STATUS)" >&2
    exit "$STATUS"
fi
mv "$BACKUP_DIR/reticle-$STAMP.tar.gz.partial" "$BACKUP_DIR/reticle-$STAMP.tar.gz"
find "$BACKUP_DIR" -name 'reticle-*.tar.gz' -mtime +14 -delete
echo "backup complete: $STAMP"
```

The archive has the same layout as the Compose one, so a backup taken here
can be restored into a Compose installation with `deploy/restore.sh` — which
is also the migration path from this setup to that one. (The Compose backup
is more careful than this script: it leaves a half-uploaded file out
altogether rather than archiving the half that happened to be there.)

Housekeeping, weekly, from the `reticle` user's crontab — the same command
`deploy/maintenance.sh` runs in the container (`MAINTENANCE.md` section 7):

```cron
30 4 * * 0 cd /opt/reticle/current/backend && RETICLE_ENV_FILE=/opt/reticle/shared/reticle.env ../venv/bin/python -m app.maintenance purge-orphans
```

## 15. When to outgrow SQLite

SQLite is right until it is not. Reticle already runs it the way that scales
furthest on one host — WAL mode, so readers never wait for a writer, and a
write lock taken up front, so two workers queue instead of failing. Consider
PostgreSQL when either becomes true:

- **Writers block each other noticeably.** Several staff authoring at once and
  seeing saves lag. SQLite allows one writer at a time.
- **You need more than one machine**, for availability rather than load.

Reading is not the trigger — most Reticle traffic is people reading guides.

**PostgreSQL is untested.** The code is written to stay compatible (SQLAlchemy
throughout, migrations in Alembic's batch mode, nothing SQLite-specific in the
queries), but no test run, no CI job and no deployment has ever used it. The
images do not contain a PostgreSQL driver, `compose.yaml` hard-wires the
SQLite path, and `deploy/backup.sh` only knows SQLite. Treat a move as a small
project: add `psycopg` to the image, add a database service, run
`app.migrate` against it, copy the content across, run the whole test suite
against it, and replace the backup script with `pg_dump`. Budget days, not an
afternoon, and do it with a backup in hand.

Do not migrate pre-emptively. A PostgreSQL instance is a second service to
back up, patch and monitor, and for a facility of this size it buys nothing
until one of the two signals above appears.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

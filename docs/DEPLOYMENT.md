# Deploying Reticle

This guide is written to be understood, not just pasted. If you know why each
piece is there, you can fix it at 4pm on a Friday when something is wrong.

## 1. What the moving parts are

Reticle is three things and a disk:

```
        the internet / ZMB network
                    │
                    ▼
        ┌───────────────────────┐
        │  nginx (or Caddy)     │   terminates HTTPS
        │                       │   serves the built frontend
        │                       │   forwards /api to uvicorn
        └───────────┬───────────┘
                    │  http://127.0.0.1:8000
                    ▼
        ┌───────────────────────┐
        │  uvicorn + FastAPI    │   the API, auth, permissions
        └───────────┬───────────┘
                    │
        ┌───────────┴───────────┐
        │  reticle.db (SQLite)  │   guides, users, history
        │  media/               │   uploaded images and step videos
        └───────────────────────┘
```

**The frontend is static files.** `npm run build` produces HTML, CSS and JS in
`frontend/dist`. There is no Node process in production. nginx serves those
files directly, which is why the site stays fast on an ordinary VM.

**The backend never serves the frontend.** It only answers `/api/...`. This is
deliberate: one process with one job is easier to reason about, and it means a
backend restart does not take the interface down, only its data.

**Same origin, so no CORS in production.** Because nginx serves both the pages
and `/api` under one hostname, the browser is making same-origin requests and
`RETICLE_CORS_ORIGINS` does not come into play at all. That setting exists for
local development, where the frontend is on port 5173 and the API on 8000.

**The database is a file.** SQLite. For one institute's editing load this is the
right answer — no separate service, no separate backup story, no separate thing
to break. Section 9 covers when that stops being true.

## Upgrading across a schema change

**This no longer needs a hand.** Reticle uses Alembic, and the release process
runs `alembic upgrade head` before the new code serves traffic. Earlier versions
of this document told you to write `ALTER TABLE` yourself; that advice is dead,
and if you find a copy of it somewhere, delete it.

What is still true, and always will be:

```bash
sudo /usr/local/bin/reticle-backup          # always first, without exception
```

The deploy pipeline does this for you (`.github/workflows/deploy.yml`), before
migrations run and while the old code is still serving. Take one by hand too if
you are doing anything unusual — it costs seconds and it is the thing that makes
every other step reversible.

Migrations in this project are **additive**: a column is added, code that writes
both is deployed, the old one is removed a release later. That is what makes
rolling back real, because the previous release can still read the new schema.
If a release ever needs a destructive migration, it does not get to run itself
on startup — see `db.init_db`.


## 2. What you need before starting

- A Linux VM (Debian or Ubuntu assumed below), 1 vCPU and 1 GB RAM is plenty.
- A DNS name pointing at it, e.g. `reticle.zmb.uzh.ch`. Ask UZH IT.
- Port 443 reachable from wherever ZMB staff will read guides.
- `sudo` on the box.

**HTTPS is not optional.** The session cookie is issued with the `Secure` flag,
which means browsers refuse to send it over plain http. Without TLS, nobody can
log in. This is a feature — it is the difference between a password crossing the
university network encrypted and in the clear.

## 3. First install

### 3.1 Create a service account and the directory layout

Reticle runs as its own unprivileged user. If the application is ever
compromised, the attacker gets that user's permissions and nothing more.

```bash
sudo adduser --system --group --home /opt/reticle reticle
sudo -u reticle mkdir -p /opt/reticle/{releases,shared,static}
```

`shared/` holds the things that must survive a deployment — the database, the
uploaded images, and the configuration. `releases/` holds each version.
Deployments swap a `current` symlink between releases, so rolling back is
instant and never touches your data.

### 3.2 Install the code

```bash
sudo apt update && sudo apt install -y python3-venv nginx git
sudo -u reticle git clone <your-repo-url> /opt/reticle/releases/first
cd /opt/reticle/releases/first
sudo -u reticle python3 -m venv venv
sudo -u reticle venv/bin/pip install -r backend/requirements.txt
sudo -u reticle ln -sfn /opt/reticle/releases/first /opt/reticle/current
```

### 3.3 Write the configuration

```bash
sudo -u reticle cp backend/.env.example /opt/reticle/shared/.env
sudo -u reticle venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
sudo -u reticle nano /opt/reticle/shared/.env
```

Set at minimum:

```ini
RETICLE_SECRET_KEY=<the value you just generated>
RETICLE_DATABASE_URL=sqlite:////opt/reticle/shared/reticle.db
RETICLE_MEDIA_ROOT=/opt/reticle/shared/media
RETICLE_COOKIE_SECURE=true
RETICLE_TRUST_FORWARDED_FOR=true
```

Note the **four** slashes in the SQLite URL — `sqlite:////opt/...` is an
absolute path; three slashes would be relative to the working directory and you
would get a second, empty database the first time systemd started you elsewhere.

`RETICLE_SECRET_KEY` is the pepper for session-token hashes. Changing it later
logs everyone out, which is occasionally exactly what you want (section 8).

`RETICLE_TRUST_FORWARDED_FOR=true` is correct **only** because nginx is going to
overwrite `X-Forwarded-For` below. Without such a proxy, this setting lets any
client pick its own rate-limit bucket and defeats the login throttle.

Lock the file down — it contains the key to every session:

```bash
sudo chmod 600 /opt/reticle/shared/.env
sudo chown reticle:reticle /opt/reticle/shared/.env
sudo -u reticle ln -sfn /opt/reticle/shared/.env /opt/reticle/current/backend/.env
```

### 3.4 Create the first administrator

```bash
cd /opt/reticle/current/backend
sudo -u reticle RETICLE_ADMIN_EMAIL=you@zmb.uzh.ch \
     RETICLE_ADMIN_PASSWORD='<a long passphrase>' \
     ../venv/bin/python -m app.seed
```

This creates the schema, the eight ZMB categories and your admin account. It is
idempotent — safe to run on every deploy — and it will never reset a password
somebody has already changed. It refuses to run without a password rather than
inventing a default, because a default admin password is how internal tools get
owned.

Unset that variable afterwards. It is only read at seed time.

### 3.5 Build the frontend

Build it on your workstation or in CI, not on the server — the server does not
need Node installed.

```bash
cd frontend && npm ci && npx vite build
rsync -av dist/ reticle@<host>:/opt/reticle/static/
```

### 3.6 Run the API under systemd

Create `/etc/systemd/system/reticle.service`:

```ini
[Unit]
Description=Reticle guide platform
After=network.target

[Service]
Type=exec
User=reticle
Group=reticle
WorkingDirectory=/opt/reticle/current/backend
EnvironmentFile=/opt/reticle/shared/.env
ExecStart=/opt/reticle/current/venv/bin/python -m uvicorn app.main:app \
          --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3

# The service needs to write exactly two things. Everything else is read-only.
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

`Restart=always` is the part people skip. A bare `uvicorn` in a terminal dies
with the terminal, and nothing brings it back. systemd restarts it on crash and
on reboot.

**`--workers 1` is deliberate.** SQLite serialises writers. One worker is
comfortably enough for a facility where a handful of people edit guides and the
rest read them. Do not raise it without first reading section 9.

Bind to `127.0.0.1`, never `0.0.0.0` — the API should be reachable only through
nginx, so the security headers and TLS cannot be bypassed by hitting port 8000
directly.

### 3.7 Put nginx in front

`/etc/nginx/sites-available/reticle`:

```nginx
server {
    listen 80;
    server_name reticle.zmb.uzh.ch;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name reticle.zmb.uzh.ch;

    ssl_certificate     /etc/letsencrypt/live/reticle.zmb.uzh.ch/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/reticle.zmb.uzh.ch/privkey.pem;

    # Guide photographs are the large things here; 25m leaves headroom above
    # the application's own 20 MB upload cap so the API can return a clean
    # error rather than nginx cutting the connection.
    client_max_body_size 25m;

    root /opt/reticle/static;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        # Overwrite, not append: this is what makes TRUST_FORWARDED_FOR safe.
        proxy_set_header X-Forwarded-For   $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Reticle is a single-page app: the server has no /c/light-microscopy file,
    # so unmatched paths must fall back to index.html or a refresh 404s.
    location / {
        try_files $uri $uri/ /index.html;
    }

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

Built asset filenames contain a content hash, so caching them for a year is safe
— a new build produces new names. `index.html` must **not** be cached that way,
which is why the rule targets `/assets/` only.

```bash
sudo ln -s /etc/nginx/sites-available/reticle /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d reticle.zmb.uzh.ch
```

Certbot renews automatically via a systemd timer. Confirm with
`systemctl list-timers | grep certbot`.

## 4. Check it actually works

```bash
curl -sf https://reticle.zmb.uzh.ch/api/health          # {"status":"ok"}
curl -si https://reticle.zmb.uzh.ch/api/guides | head -1 # 401 — correct
```

That 401 is the single most important check on this page. It proves the site is
behind the login. If it ever returns 200, stop and investigate.

Then open the site, sign in, create a test guide, upload an image, publish it,
and read it on your phone.

## 5. Updating

With the pipeline (`.github/workflows/deploy.yml`), tag a release and it ships:

```bash
git tag v1.1.0 && git push origin v1.1.0
```

By hand:

```bash
NEW=/opt/reticle/releases/$(date +%Y%m%d-%H%M)
sudo -u reticle git clone --depth 1 <repo> $NEW
cd $NEW && sudo -u reticle python3 -m venv venv
sudo -u reticle venv/bin/pip install -r backend/requirements.txt
sudo -u reticle ln -sfn /opt/reticle/shared/.env $NEW/backend/.env
sudo -u reticle ln -sfn $NEW /opt/reticle/current
sudo systemctl restart reticle
curl -sf https://reticle.zmb.uzh.ch/api/health
```

**Back up before every update** (see `MAINTENANCE.md`). It takes ten seconds and
is the difference between an inconvenience and a bad week.

## 6. Rolling back

```bash
ls /opt/reticle/releases
sudo -u reticle ln -sfn /opt/reticle/releases/<previous> /opt/reticle/current
sudo systemctl restart reticle
```

This works because the database and images live in `shared/`, outside any
release. Rolling back the code does not roll back content — which is what you
want, since guides written since the update are real work.

The exception is a release that changed the database schema. Reticle adds
missing tables on startup but never drops or rewrites columns, so a rollback is
safe unless a release explicitly says otherwise in its notes.

## 7. Where things are

| Thing | Path |
| --- | --- |
| Live code | `/opt/reticle/current` (symlink) |
| Configuration | `/opt/reticle/shared/.env` |
| Database | `/opt/reticle/shared/reticle.db` |
| Uploaded images and videos | `/opt/reticle/shared/media/` |
| Built frontend | `/opt/reticle/static/` |
| Logs | `journalctl -u reticle` |
| Web server config | `/etc/nginx/sites-available/reticle` |

## 8. Rotating the secret

If `RETICLE_SECRET_KEY` is ever exposed — pasted into a ticket, committed by
accident, on a stolen laptop — generate a new one, put it in
`/opt/reticle/shared/.env`, and restart. Every session becomes invalid and
everyone signs in again. Passwords are unaffected; they are hashed with Argon2id
independently of this key.

## 9. When to outgrow SQLite

SQLite is right until it is not. Move to PostgreSQL when either becomes true:

- **Writers block each other noticeably.** Several staff authoring
  simultaneously and seeing saves lag. SQLite allows one writer at a time.
- **You need more than one worker or more than one machine**, for availability
  rather than load.

Reading is not the trigger — SQLite handles concurrent readers fine, and most
Reticle traffic is people reading guides.

The migration is: install PostgreSQL, `pip install psycopg[binary]`, point
`RETICLE_DATABASE_URL` at it, run `python -m app.seed` against the empty
database, and copy the content across. Nothing in the application code changes;
SQLAlchemy handles both. Budget an afternoon and do it with a backup in hand.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

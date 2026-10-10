# Reticle backend

FastAPI + SQLAlchemy + SQLite implementation of the HTTP contract in
[`../docs/API.md`](../docs/API.md). The domain model it serialises is
[`../frontend/src/domain/types.ts`](../frontend/src/domain/types.ts); that file
is authoritative, and this backend translates its snake_case columns to
camelCase so the frontend never has to.

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT (see `../LICENSE`)

## Quick start (Linux)

```bash
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # add -r requirements-dev.txt to run the tests

cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # paste into RETICLE_SECRET_KEY

python -m app.migrate                    # create or upgrade the schema
RETICLE_ADMIN_PASSWORD='<a long passphrase>' python -m app.seed
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

For local http development also set `RETICLE_COOKIE_SECURE=false`, otherwise the
browser will not return the session cookie over a plain connection. The Vite
dev server proxies `/api` to `127.0.0.1:8000`, so the two share an origin.

Python 3.12 or newer. The PDF export looks for DejaVu Sans (`fonts-dejavu-core`
on Debian/Ubuntu, `ttf-dejavu` on Alpine) and falls back to a font bundled with
ReportLab, which lacks some scientific glyphs (λ, Å, ≥); install the package in
a container image.

## Environment on the ZMB Windows machines

The environment is built from **conda-forge only**. The `defaults` channel is
not used anywhere in this project.

```powershell
C:\ProgramData\MinicondaZMB\Scripts\conda.exe create -y -n reticle `
  --override-channels -c conda-forge `
  python=3.12 fastapi uvicorn sqlalchemy alembic pydantic pydantic-settings `
  argon2-cffi pillow reportlab python-multipart python-ulid email-validator `
  pytest pytest-cov httpx pypdf
```

The environment lives under `C:\ProgramData\MinicondaZMB\envs\reticle`, which is
AppLocker-whitelisted on the ZMB machines. Do not relocate it under a
user-writable path — executables there will not run. Every command below works
there with `C:\ProgramData\MinicondaZMB\envs\reticle\python.exe` in place of
`python`:

```powershell
Copy-Item .env.example .env
$py = "C:\ProgramData\MinicondaZMB\envs\reticle\python.exe"
& $py -c "import secrets; print(secrets.token_urlsafe(48))"
& $py -m app.migrate
$env:RETICLE_ADMIN_PASSWORD = "<a long passphrase>"; & $py -m app.seed
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

## Configuration

`.env.example` documents every variable; all are prefixed `RETICLE_`. The
application refuses to start without `RETICLE_SECRET_KEY`, because it is the
pepper for session-token hashes and a shipped default would be identical on
every installation. The ones worth a second look:

| Variable | Why it matters |
| --- | --- |
| `RETICLE_SECRET_KEY` | Mandatory, at least 16 characters. Pepper for session-token digests; also signs the login throttle's device cookie. |
| `RETICLE_ENV_FILE` | Where the env file lives. Defaults to `.env` in the working directory; set it empty to use the process environment only (containers). |
| `RETICLE_DATABASE_URL` | Default `sqlite:///./reticle.db`. Read by the server, `app.migrate` and `app.seed` alike. |
| `RETICLE_MEDIA_ROOT` | Must sit **outside** any directory a web server serves. Images and videos are delivered through `/api/media/{id}`, behind the login. Default `./media`. |
| `RETICLE_COOKIE_SECURE` | `true` in production (also switches on HSTS). `false` only for local http. |
| `RETICLE_CORS_ORIGINS` | Exact origins only. A `*` is refused at start-up: with credentialed cookies it would let any website read the API as the signed-in user. |
| `RETICLE_TRUSTED_PROXIES` | Addresses or CIDR blocks of the reverse proxies in front of the API. `X-Forwarded-For` is believed only on connections from these, and is read from the right. Empty means the header is ignored. See "Behind a reverse proxy". |
| `RETICLE_MAX_REQUEST_BYTES` | Ceiling on every request body except an upload. Default 2 MB. |
| `RETICLE_MAX_UPLOAD_BYTES` | One image. Default 20 MB. |
| `RETICLE_MAX_VIDEO_BYTES` | One video. Default 200 MB; the reverse proxy must allow a body this large. |
| `RETICLE_MAX_IMAGE_PIXELS` | Width × height an image may declare, checked before anything decodes. Default 40 megapixels. |
| `RETICLE_LOGIN_MAX_ATTEMPTS_*` | The three login throttle limits and their window. |
| `RETICLE_DEBUG` | Development only: serves `/docs`, `/redoc` and `/openapi.json`, unauthenticated. Off by default. |
| `RETICLE_ADMIN_EMAIL`, `RETICLE_ADMIN_PASSWORD` | Read once by the seeder. Unset the password afterwards. |
| `RETICLE_DEMO_PASSWORD` | Only for `app.seed --demo`: when set, also creates a demo author and a demo viewer with this password. |

`RETICLE_TRUST_FORWARDED_FOR` no longer exists as a switch; the server refuses
to start if it is set without `RETICLE_TRUSTED_PROXIES`.

## Database and migrations

The schema is owned by Alembic (`migrations/`, one baseline revision).

```bash
python -m app.migrate        # create on an empty database, upgrade an existing one; safe on every deploy
```

`alembic upgrade head` from this directory does the same thing; `alembic
revision --autogenerate -m "..."` writes the next migration. Both read
`RETICLE_DATABASE_URL` through the application's settings. Migrations run in
batch mode, so the same scripts work on SQLite and PostgreSQL.

The server does not migrate at start-up: it checks, and refuses to start with
an instruction when the schema is missing or at another revision. A database
created by a development build from before migrations existed is refused too —
there is no upgrade path from it, so move it aside.

SQLite is opened in write-ahead (WAL) mode with a five-second busy timeout and
foreign keys on, and every mutating request takes the write lock up front
(`BEGIN IMMEDIATE`), so two workers queue instead of failing. The database is
therefore three files (`reticle.db`, `-wal`, `-shm`): back it up with
`sqlite3 reticle.db ".backup copy.db"`, not by copying one file. The code is
kept PostgreSQL-compatible; to switch, install a driver (`psycopg`) and change
the URL.

## Seeding

```bash
RETICLE_ADMIN_PASSWORD='<a long passphrase>' python -m app.seed
```

Creates the administrator, the eight ZMB categories and one worked example
guide. It runs the migrations first, is idempotent — safe on every deploy — and
never resets a password an operator has already changed. It **refuses** to run
without `RETICLE_ADMIN_PASSWORD` on a first install rather than falling back to
a known default.

```bash
RETICLE_ADMIN_PASSWORD='...' RETICLE_DEMO_PASSWORD='...' python -m app.seed --demo
```

Demo mode is opt-in and for a test or evaluation instance. On top of the above
it creates a hidden holding category, three more guides (two published, one
draft; the tile-scan guide carries annotated placeholder screenshots drawn by
Pillow), several tags,
landing pages for *Light Microscopy* and *Sample Preparation* that embed
`guidelist` blocks, a standalone wiki page and a draft landing page. When
`RETICLE_DEMO_PASSWORD` is set it also creates `demo.author@<domain>` and
`demo.viewer@<domain>` with that password, `<domain>` being the one in
`RETICLE_ADMIN_EMAIL`; no demo account has a built-in password.

## Running

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Add `--reload` while developing. `GET /api/health` runs a trivial query and
answers `{"status": "ok"}`, or 503 when the database does not respond; it needs
no session and is what a container healthcheck should call.

More than one worker is supported on SQLite (writes queue), though one is
plenty for an institute; move to PostgreSQL before scaling out further.

### Behind a reverse proxy

- **Client addresses.** Set `RETICLE_TRUSTED_PROXIES` to the proxy's address or
  network (in Docker Compose, the subnet of the network the proxy container
  reaches the API over, e.g. `172.16.0.0/12` or a fixed subnet you assign) and
  keep `--no-proxy-headers` on uvicorn, so Reticle's explicit list is the only
  thing that decides whose `X-Forwarded-For` is believed. Without the list every
  user appears to come from the proxy and shares one login-throttle bucket.
- **Body size.** The proxy must accept `RETICLE_MAX_VIDEO_BYTES` plus about
  1 MB of multipart overhead on `POST /api/media` (Caddy: `request_body {
  max_size 210MB }`; nginx: `client_max_body_size 210m;` and preferably
  `proxy_request_buffering off;`). Everything else fits in 2 MB. Allow a
  generous read timeout on that route: 200 MB over a slow uplink takes minutes.
  The upload is spooled to the system temp directory before it is copied into
  the media root, so `/tmp` (or `TMPDIR`) needs room for one video per
  concurrent upload.
- **Range requests.** `GET /api/media/{id}` answers `Range` with 206, which is
  what lets a video seek. Do not let the proxy cache or buffer that route in a
  way that strips `Range`, and do not serve the media directory directly —
  visibility is decided per request.
- **TLS.** Terminate it at the proxy and keep `RETICLE_COOKIE_SECURE=true`.

## Tests

```bash
python -m pytest
python -m pytest --cov=app --cov-report=term-missing     # fails under 95 % branch coverage
```

Each test gets a private database and a private media directory, so the suite
is order-independent even though sessions, the login throttle and uploaded
files are all persistent state. The environment variables the tests need are
set at the top of `tests/conftest.py`; no `.env` is required to run them.

## Layout

| Module | Responsibility |
| --- | --- |
| `app/main.py` | App factory, request-size, CSRF and security-header middleware, error translation, health, the route-guard sweep. |
| `app/settings.py` | Environment-backed configuration and the start-up refusals. |
| `app/db.py` | Engine (SQLite tuning), session lifecycle, UTC and JSON column types. |
| `app/models.py` | ORM entities. Guides and pages share `ContentMixin`. |
| `app/schemas.py` | camelCase wire format, input ceilings, ORM → wire serialisers. |
| `app/auth.py` | Authentication and role dependencies; the client-address rule. |
| `app/security.py` | Argon2id hashing, session tokens, login throttle, pruning. |
| `app/content.py` | The lifecycle guides and pages share: visibility predicate, concurrency token, publish/unpublish/archive/view/revisions. |
| `app/documents.py` | The whole-guide `PUT`: steps, bullets, media, annotations, tags; publish rules. |
| `app/pages.py` | The whole-page `PUT`: landing slot, hero, media references in the body. |
| `app/images.py` | Image validation by decode, pixel caps, EXIF stripping, safe storage paths. |
| `app/videos.py` | MP4/WebM recognition by container signature; streamed storage. |
| `app/pdf.py` | The guide as an A4 PDF (ReportLab). |
| `app/audit.py` | The who-changed-what trail. |
| `app/migrate.py` | `python -m app.migrate`; the start-up schema check. |
| `app/seed.py` | First-run data and the demo dataset. |
| `app/routers/` | One module per resource in the contract. |
| `migrations/` | Alembic environment and revisions. |

## Security notes

- **Passwords** are Argon2id (`argon2-cffi`), RFC 9106 profile by default.
  Plaintext is never stored, never logged and never accepted into an audit
  record — `app/audit.py` raises if a secret-bearing key reaches it.
- **Sessions** are opaque 256-bit tokens in an httpOnly, `SameSite=Lax`, Secure
  cookie. Only an HMAC-SHA256 digest is stored, so a leaked database backup does
  not yield live sessions. Logout is a server-side revocation. Expired and
  revoked sessions are deleted a week after they die, and login-attempt rows
  once they leave the window — at start-up and, at most every ten minutes, from
  the login path.
- **CSRF** is checked twice. Middleware compares `X-CSRF-Token` against the
  `reticle_csrf` cookie in constant time; the session dependency then checks
  that the cookie is the one issued for *this* session. `POST /api/auth/login`
  is exempt, because a request that establishes a session cannot echo a token
  it has not yet been given.
- **Login throttling** counts failures per (account, source), per source (an
  IPv6 source is its /64) and per account, with an identical response and an
  identical amount of Argon2 work for an unknown email and a wrong password.
  A browser that has signed in to an account before carries a signed
  `reticle_device` cookie and is counted only against its own allowance, so
  nobody can lock a colleague out of the machine they normally use by guessing
  at their account. What remains: while an account is under a distributed
  attack (50 failures in 15 minutes), sign-in from a browser that account has
  *never* used is refused, and people who share one source address share its
  spray limit (20) on first-time browsers.
- **Visibility** is one SQL predicate (`content.visible_to`), applied to
  listings, single reads, search, tag counts, landing pages and the PDF. Media
  bytes follow it: a viewer can fetch a file only while a published guide step,
  or the hero or body of a published page, shows it.
- **Uploads.** Images are validated by decoding, never by filename or declared
  MIME, with the per-side and total-pixel limits applied from the header before
  anything is decoded (and an all-frames budget for animations); they are
  re-encoded, which strips EXIF. Videos are recognised by container signature
  (ISO-BMFF `ftyp` with a playable brand, or EBML with doctype `webm`), streamed
  to disk against the cap and stored as uploaded. Files live under a generated
  ULID path, and are served with `nosniff` and a sandboxing CSP.
- **Ceilings.** Request bodies are limited by declared length and again as they
  arrive (chunked bodies included); only `POST /api/media` gets the larger
  limit. Documents are bounded: 200 steps, 200 bullets per step, 3 media per
  step, 50 annotations per image, 30 tags, 200 000 characters of page body.
- **Headers.** Every response carries `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, a deny-all CSP,
  `Cache-Control: no-store` unless the endpoint says otherwise, and HSTS when
  cookies are Secure.
- **Authorisation** is a dependency on every route.
  `test_every_route_is_behind_authentication` fails if a route is added
  without one, and the generated API documentation is not mounted outside
  debug mode.

## Where the contract needed interpreting

Recorded here rather than silently absorbed:

1. **Tag names.** The first spelling the server sees becomes `Tag.name`. The
   editor's tag input sends slugs, so a tag created there is named by its slug;
   a client that sends `"LAS X"` gets the name `LAS X` and the slug `las-x`.
2. **Archived content is not listable.** `status=archived` returns an empty
   list for every role, because the visibility rule says nobody sees the
   archive. Archived rows still count when deleting a category.
3. **Publishing a published guide or page republishes it**: the version
   increments and a new snapshot is written. Unpublishing something that is not
   published is 409 `conflict`.
4. **`publishedBy` in the revision list is a `UserRef`**, as in
   `frontend/src/api/reticle.ts`.
5. **Media references in a page body** are any occurrence of
   `/api/media/<id>`, not only `![alt](...)` image syntax, so reference-style
   images and links to videos are recorded too. References to files that do not
   exist are ignored rather than refused.
6. **`q` on `GET /api/pages`** matches title and summary; the body is searched
   by `/api/search` only. `q` on `GET /api/guides` also matches tag slugs.
7. **Annotation ids** from the client are kept (letters, digits, `-`, `_`, at
   most 64 characters) and minted when absent; they need only be unique within
   their image.
8. **`GET /api/categories/{id}/page`** is 404 for a category that does not
   exist, and `null` for one that exists without a visible landing page.
9. **The PDF export** renders at most two documents at a time per worker and
   answers 429 `rate_limited` if a slot does not come free within 20 seconds.
10. **`reticle_device`** is a third cookie (httpOnly, path `/api/auth`) that the
    contract does not mention; it only feeds the login throttle.
11. **Timestamps** always carry six fractional digits, because `updatedAt` is
    the concurrency token and has to round-trip exactly.

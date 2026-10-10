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
| `RETICLE_MAX_MEDIA_STORE_BYTES` | Total size of stored uploads at which new ones are refused with 413. Default `0`, no limit. Measured as the sum of the originals recorded in the database; display copies and the PDF cache are not counted, so leave headroom. |
| `RETICLE_PDF_CACHE_DIR` | Where rendered PDFs of published guides are kept. Default: `.pdf-cache` inside the media root. Must be writable; nothing in it needs backing up, and it can be emptied at any time. |
| `RETICLE_LOGIN_MAX_ATTEMPTS_*` | The three login throttle limits and their window. |
| `RETICLE_DEBUG` | Development only: serves `/docs`, `/redoc` and `/openapi.json`, unauthenticated. Off by default. |
| `RETICLE_ADMIN_EMAIL`, `RETICLE_ADMIN_PASSWORD` | Read once by the seeder. Unset the password afterwards. |
| `RETICLE_DEMO_PASSWORD` | Only for `app.seed --demo`: when set, also creates a demo author and a demo viewer with this password. |

`RETICLE_TRUST_FORWARDED_FOR` no longer exists as a switch; the server refuses
to start if it is set without `RETICLE_TRUSTED_PROXIES`.

## Database and migrations

The schema is owned by Alembic (`migrations/`).

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

Revision `0004` changes what readers are served (see "Working copy and
published snapshot" below) and fills the new index tables from each published
item's latest snapshot. On a database where a published guide was edited after
its last publish, readers go back to the version that was published and the
guide shows "unpublished changes" to its authors; nothing is lost.

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

## Maintenance

```bash
python -m app.maintenance purge-orphans                      # uploads unused for 7 days or more
python -m app.maintenance purge-orphans --older-than-days 30
python -m app.maintenance purge-orphans --dry-run            # report only, change nothing
```

Deletes what Reticle keeps and nothing uses any more, and prints one line per
kind:

- **uploads nothing shows** — in no guide step, no page body, no page hero, and
  no published version past or present — that are at least N days old, with
  their files and display copies. The age is what tells an abandoned upload
  from one an author has just dropped in and not yet saved;
- **files in the media directory no upload owns**, at least N days old;
- **expired sessions and old login-attempt rows**;
- **cached PDF exports** of anything that is not the current published version;
- **index rows** of content that is no longer published.

It reads the same environment as the server, is safe to run while the server
is up, and is safe to run twice. It never touches a guide, a page, a published
version or anything one of them shows. A weekly timer is plenty. Exit status 0
on success, 1 when the database schema is not current, 2 on a usage error.

To remove one specific upload that *is* in use — the badge photographed by
accident — an administrator calls `DELETE /api/media/{id}?force=true`
(`docs/API.md`, "Deleting"). Neither that nor this command reaches into
backups already taken.

## Running

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Add `--reload` while developing. `GET /api/health` runs a trivial query and
answers `{"status": "ok"}`, or 503 when the database does not respond; it needs
no session and is what a container healthcheck should call.

More than one worker is supported on SQLite (writes queue), though one is
plenty for an institute; move to PostgreSQL before scaling out further.

Limits that are **per worker process**, because they live in memory: two PDF
renders at a time, one PDF render per signed-in user, and one image being
decoded at a time (an upload, or the first request for a display copy). With
two workers the totals are twice that. Each worker runs requests on 40 threads
and keeps a pool of up to 50 database connections (10 kept open), so the
connection pool cannot be exhausted by slow requests.

Memory: decoding an image costs four bytes a pixel for as long as it takes, so
a 40-megapixel upload peaks at about 200 MB in the worker handling it. Nothing
else comes close; a PDF export works from display copies and stays in the tens
of megabytes however large the originals are.

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
- **Caching.** Media is sent `Cache-Control: private, no-cache` with an `ETag`
  and answers `If-None-Match` with 304. Do not have the proxy cache `/api`, and
  do not have it strip or rewrite `ETag` / `If-None-Match` (a proxy that
  compresses responses may weaken the tag, which is fine).
- **Writable paths.** The API writes to the media root (uploads, display
  copies, and by default the PDF cache under `.pdf-cache`) and to the temp
  directory. On a read-only root filesystem both must be on a writable volume.
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
| `app/content.py` | The lifecycle guides and pages share: visibility predicate, who is served the working copy and who the snapshot, concurrency token, publish/unpublish/revert/archive/view/revisions. |
| `app/published.py` | The published side: serving a snapshot, the `published_*` index written at each publish, comparing a working copy with its snapshot, restoring one. |
| `app/documents.py` | The whole-guide `PUT`: steps, bullets, media, annotations, tags; publish rules. |
| `app/pages.py` | The whole-page `PUT`: landing slot, hero, media references in the body. |
| `app/images.py` | Image validation by decode, pixel caps, what is kept byte for byte and what is re-encoded, display copies, safe storage paths. |
| `app/uploads.py` | The stored uploads as a collection: what uses each one, removing one, the store's size ceiling. |
| `app/maintenance.py` | `python -m app.maintenance purge-orphans`. |
| `app/videos.py` | MP4/WebM recognition by container signature; streamed storage. |
| `app/pdf.py` | The guide as an A4 PDF (ReportLab); render slots and the on-disk cache of published exports. |
| `app/audit.py` | The who-changed-what trail. |
| `app/migrate.py` | `python -m app.migrate`; the start-up schema check. |
| `app/seed.py` | First-run data and the demo dataset. |
| `app/routers/` | One module per resource in the contract. |
| `migrations/` | Alembic environment and revisions. |

## Working copy and published snapshot

The rows a guide or page is stored in — with its steps, bullets and media
links — are its **working copy**: what the editor loads and autosaves into.
Every publish writes an immutable **snapshot** (`guide_revisions`,
`page_revisions`), and that snapshot, not the rows, is what a viewer is served
until the next publish. "Editing a published guide never breaks the version
people are reading" rests on that and on nothing else.

Serving one guide from a JSON snapshot is easy; asking "which published guides
carry this tag" of several hundred of them is not. So each publish also writes,
in the same transaction, a small relational projection of the snapshot:

| Table | Holds |
| --- | --- |
| `published_guides` | one row per currently published guide: the snapshot's title, summary, category, difficulty, time, step count, its search text, and which revision it is |
| `published_guide_tags` | the snapshot's tags |
| `published_guide_media` | the uploads the snapshot shows |
| `published_pages`, `published_page_media` | the same for pages (the body is the search text; media are the hero and the body's references) |

Every reader-facing query is a `WHERE` clause over those tables joined to the
item — listings, tag filters, tag counts, search, landing pages, and the
predicate that decides whether a viewer may fetch a media file. A viewer's
listing opens no snapshot, and costs the same number of statements for eighty
guides as for two. Unpublishing and archiving delete the rows; every query also
tests the status, so a writer that changes a status without going through
`content` (the importer does) cannot leave a withdrawn guide visible.

`content.write_revision` is the single place a snapshot is written, and it
writes the projection with it. The publish endpoint, the demo seed and the
importer all end there.

`guides.snapshot_updated_at` / `pages.snapshot_updated_at` hold the
`updated_at` at which the working copy last read the same as its snapshot.
`hasUnpublishedChanges` is the two differing, which a listing can compute
without opening anything. A save compares the saved copy with the snapshot and
brings the marker up to date when they match; counting a view touches neither
column.

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
  identical amount of Argon2 work for an unknown or deactivated account and a
  wrong password; a request over a limit is refused before any hashing.
  A browser that has signed in to an account before carries a signed
  `reticle_device` cookie. It is not turned away by the counters that other
  people can fill — a shared address's noise, a distributed guess at the
  account — so nobody can lock a colleague out of the machine they normally
  use. It is counted against its own allowance (5), all of an account's
  devices together against the account ceiling (50), and its attempts still
  count towards the ceiling strangers are held to. The cookie is signed over
  its issue time and the account's `auth_epoch`: it expires after 180 days and
  dies when the password is changed or reset or the account is deactivated
  (`security.end_credentials`, which also revokes the sessions). What remains:
  while an account is under a distributed attack (50 failures in 15 minutes),
  sign-in from a browser that account has *never* used is refused, and people
  who share one source address share its spray limit (20) on first-time
  browsers. **Anything that sets a password outside the API must call
  `security.end_credentials`** as well, or old sessions and device cookies
  survive the change.
- **Visibility** has two halves. *Which items*: one SQL predicate
  (`content.visible_to`). *Which text*: a viewer is served the published
  snapshot and never the working copy (`content.serves_published`). Both are
  applied to single reads, listings, search, tag counts, landing pages and the
  PDF. Media bytes follow them: a viewer can fetch a file only while the
  published snapshot of a currently published guide or page shows it.
- **Uploads.** Images are validated by decoding, never by filename or declared
  MIME, with the per-side and total-pixel limits applied from the header before
  anything is decoded (and an all-frames budget for animations). A file that is
  nothing but a picture is stored as uploaded; one that carries anything else
  (EXIF, XMP, comments, text chunks, trailing bytes) is re-encoded, which strips
  it — "nothing but a picture" is decided by walking the container against a
  list of what is allowed. Videos are recognised by container signature
  (ISO-BMFF `ftyp` with a playable brand, or EBML with doctype `webm`), streamed
  to disk against the cap and stored as uploaded. Files live under a generated
  ULID path, and are served with `nosniff`, a sandboxing CSP, and
  `Cache-Control: private, no-cache` so that a cached copy is revalidated
  against the session. An upload can be deleted, and forced out of every
  version by an administrator.
- **Failures.** An exception nobody handled answers 500 in the contract's
  envelope with a fixed message; the log line names the method, the path and
  the exception type and nothing from the request. The engine is created with
  `hide_parameters`, so a logged SQL error shows the statement without the
  values that were bound to it. An unanticipated integrity error is 409, and
  only the first line of the driver's message is logged.
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
   most 64 characters) and minted when absent; like step and bullet ids they
   must be unique across the whole guide.
8. **`GET /api/categories/{id}/page`** is 404 for a category that does not
   exist, and `null` for one that exists without a visible landing page.
9. **The PDF export** renders at most two documents at a time per worker and
   one per user, and answers 429 `rate_limited` with `Retry-After` at once when
   it cannot start; the export of a published version is cached on disk.
10. **A slug never changes** after creation — not on save, not on publish.
11. **Author-facing listings, filters, tag counts and search read the working
    copy**; only `?view=published` on a single read, a landing page or the PDF
    shows an author what readers get.
12. **Reverting** is refused (409) for anything not currently published, even
    if it has older versions: readers are being shown nothing, so there is no
    "what readers see" to go back to.
13. **Timestamps** always carry six fractional digits, because `updatedAt` is
    the concurrency token and has to round-trip exactly.

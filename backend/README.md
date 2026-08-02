# Reticle backend

FastAPI + SQLAlchemy + PostgreSQL implementation of the HTTP contract in
[`../docs/API.md`](../docs/API.md). The domain model it serialises is
[`../frontend/src/domain/types.ts`](../frontend/src/domain/types.ts); that file
is authoritative, and this backend translates its snake_case columns to
camelCase so the frontend never has to.

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Licence: MIT (see `../LICENSE`)

## Environment

The environment is built from **conda-forge only**. The `defaults` channel is
not used anywhere in this project.

```powershell
C:\ProgramData\MinicondaZMB\Scripts\conda.exe create -y -n reticle `
  --override-channels -c conda-forge `
  python=3.12 fastapi uvicorn sqlalchemy pydantic pydantic-settings `
  argon2-cffi pillow python-multipart python-ulid pytest pytest-cov httpx
```

Every package resolved from conda-forge; nothing needed a pip fallback.

The environment lives under `C:\ProgramData\MinicondaZMB\envs\reticle`, which is
AppLocker-whitelisted on the ZMB machines. Do not relocate it under a
user-writable path — executables there will not run.

## Configuration

```powershell
Copy-Item .env.example .env
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put that value in `RETICLE_SECRET_KEY`. The application refuses to start
without it, because it is the pepper for session-token hashes and a shipped
default would be identical on every installation.

Set `RETICLE_DATABASE_URL` to a PostgreSQL database as well. It has no default
either: a working one would let a misconfigured server come up against a
database nobody meant to use and serve an empty library.

```powershell
$env:RETICLE_DATABASE_URL = "postgresql+psycopg://reticle:<password>@localhost/reticle"
```

For local http development also set `RETICLE_COOKIE_SECURE=false`; otherwise
the browser will not return the session cookie over a plain connection.

`.env.example` documents every variable. The ones worth a second look:

| Variable | Why it matters |
| --- | --- |
| `RETICLE_SECRET_KEY` | Mandatory. Pepper for session-token digests. |
| `RETICLE_DATABASE_URL` | Mandatory. `postgresql+psycopg://user:password@host/database`. PostgreSQL is the only engine. |
| `RETICLE_ENV_FILE` | Where this file lives. Defaults to `.env` in the working directory; point it at `/etc/reticle/reticle.env` under a service manager, or set it empty to use the process environment only. |
| `RETICLE_MEDIA_ROOT` | Must sit **outside** any directory a web server serves, and must be covered by `.gitignore`. Images are delivered through `/api/media/{id}`, behind the login. Default `./media`. |
| `RETICLE_COOKIE_SECURE` | `true` in production. `false` only for local http. |
| `RETICLE_TRUST_FORWARDED_FOR` | Enable **only** behind a proxy that overwrites `X-Forwarded-For`. Otherwise clients pick their own rate-limit bucket. |
| `RETICLE_ADMIN_PASSWORD` | Read once by the seeder. Unset it afterwards. |

## First run

```powershell
$env:RETICLE_ADMIN_PASSWORD = "<a long passphrase>"
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m app.seed
```

Seeding creates the schema, the ZMB categories — including one hidden holding
category, because that is how the real corpus is arranged — an admin account,
one worked example guide with tags, and a published category landing page whose
body embeds tag-filtered guide lists. It is idempotent, so it is safe on every deploy, and it
never resets a password an operator has already changed. It **refuses** to run
without `RETICLE_ADMIN_PASSWORD` rather than falling back to a known default.

## Running

```powershell
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Add `--reload` while developing. Interactive docs are at `/docs`, and only when
`RETICLE_DEBUG=true` — on a deployed instance they published the whole route
inventory to anybody who asked, unauthenticated.

Behind a reverse proxy, terminate TLS there, keep `RETICLE_COOKIE_SECURE=true`,
and set `RETICLE_TRUST_FORWARDED_FOR=true` only if the proxy rewrites the
header.

## Tests

```powershell
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m pytest
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m pytest --cov=app --cov-report=term-missing
```

The suite needs a PostgreSQL server, because the application does — see the
top of `tests/conftest.py` for the URL it uses and `RETICLE_TEST_DATABASE_URL`
to point it somewhere else. It empties that database at the start of the run,
so give it one of its own.

Each test gets an empty database and a private media directory, so the suite is
order-independent even though sessions, the login throttle and uploaded files
are all persistent state. The other environment variables the tests need are
set at the top of `tests/conftest.py`; no `.env` is required to run them.

## Layout

| Module | Responsibility |
| --- | --- |
| `app/main.py` | App factory, CSRF and security-header middleware, error translation, route-guard audit. |
| `app/settings.py` | Environment-backed configuration. |
| `app/db.py` | Engine, session lifecycle, UTC and JSON column types. |
| `app/models.py` | ORM entities. |
| `app/schemas.py` | camelCase wire format and the ORM → wire serialisers. |
| `app/auth.py` | Authentication and role dependencies. |
| `app/security.py` | Argon2id hashing, session tokens, login throttle. |
| `app/documents.py` | The whole-guide and whole-page `PUT`: renumbering, media cap, tags, annotations, concurrency, contributors. |
| `app/images.py` | Image upload decoding, EXIF stripping, safe storage paths. |
| `app/videos.py` | Video identification from header bytes, and why it is not re-encoded. |
| `app/audit.py` | The who-changed-what trail. |
| `app/seed.py` | First-run data, including one worked guide and a category landing page. |
| `app/routers/` | One module per resource in the contract. |
| `app/importer/` | The migration tool. Nothing in `app` imports it; see `../docs/MIGRATION.md`. |

## Security notes

- **Passwords** are Argon2id (`argon2-cffi`), RFC 9106 profile by default.
  Plaintext is never stored, never logged and never accepted into an audit
  record — `app/audit.py` raises if a secret-bearing key reaches it.
- **Sessions** are opaque 256-bit tokens in an httpOnly, `SameSite=Lax`, Secure
  cookie. Only an HMAC-SHA256 digest is stored, so a leaked database backup does
  not yield live sessions. Logout is a server-side revocation.
- **CSRF** is checked twice. Middleware compares `X-CSRF-Token` against the
  `reticle_csrf` cookie in constant time; the session dependency then checks
  that the cookie is the one issued for *this* session, which closes the
  cookie-injection hole in plain double-submit. `POST /api/auth/login` is
  exempt, because a request that establishes a session cannot echo a token it
  has not yet been given.
- **Login** is throttled per email and per source address, with an identical
  response and an identical amount of Argon2 work for an unknown email and a
  wrong password, so the endpoint is not an account-enumeration oracle.
- **Uploads** are validated by decoding, never by filename or declared MIME.
  Accepted image formats are PNG, JPEG, WebP and GIF; the file is re-encoded,
  which strips EXIF, and stored under a generated ULID path so a hostile
  filename cannot traverse. A pixel-product cap applies before decode, because a
  per-side limit is not a memory limit.
- **Video** is identified from its own header bytes (MP4 `ftyp` with a known
  brand, WebM's EBML magic) under a separate, larger cap, and is *not*
  re-encoded — that would mean shipping ffmpeg onto AppLocker-managed machines
  for no gain, since the bytes are served back with a fixed `Content-Type` and
  `nosniff` either way. This is a smaller guarantee than the image path gives
  and is a deliberate, recorded acceptance.
- **Media delivery is gated by content visibility, not only by the login.** A
  viewer gets 404 for a file unless a published guide or page actually shows
  it — as a step image, as a step video, or as a page's hero image. Each of
  those three was a separate copy of the same hole.
- **Authorisation** is a dependency on every route.
  `test_every_api_route_is_behind_authentication` fails if a new route is added
  without one.

## Deviations from the contract

Recorded here rather than silently absorbed:

1. **`slug`, `status` and `version` are read-only in `PUT /api/guides/{id}`.**
   The editor round-trips the whole guide object, so these arrive in the body;
   they are ignored. Status moves through publish/unpublish only, and a mutable
   slug would break every link a ZMB guide is cited by.
2. **`publishedBy` is a `UserRef` object**, not a bare id. The contract writes
   `{version, publishedAt, publishedBy}` without saying which; an object matches
   how every other user reference in the model is shaped.
3. **No separate draft revision of a published guide.** Editing is in place, and
   `GuideRevision` is immutable publish history — which is exactly what
   `POST /publish` and `GET /revisions/{version}` describe. Implementing a
   parallel-draft model would need new endpoints and a contract change; doing
   half of it would let a reader see a new title in a listing and the old one on
   the page.
4. **`GET /api/guides` excludes archived guides** unless `status=archived` is
   asked for explicitly. Archiving is a soft delete, so a default listing that
   still contained the archived guides would make the delete look broken.

## Migrating from the vendor

`app/importer/` reads the vendor API and writes the corpus into these models.
It is an operator tool: nothing in `app` imports it, and it only runs by hand.

```powershell
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m app.importer.run `
    --base-url https://zmb.dozuki.com --dry-run --report dry-run.txt
```

It refuses to guess. Any bullet colour, flag, shape, difficulty, time format or
media type it does not recognise stops the run and is listed in the report, and
the reconciliation counts come from the raw payload rather than from the mapped
document — so a value the mapping failed to read cannot disappear from both
sides of the comparison at once. `../docs/MIGRATION.md` has the field-by-field
mapping and the verification checklist.

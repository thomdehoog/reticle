# Reticle backend

FastAPI + SQLAlchemy + SQLite implementation of the HTTP contract in
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

For local http development also set `RETICLE_COOKIE_SECURE=false`; otherwise
the browser will not return the session cookie over a plain connection.

`.env.example` documents every variable. The ones worth a second look:

| Variable | Why it matters |
| --- | --- |
| `RETICLE_SECRET_KEY` | Mandatory. Pepper for session-token digests. |
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

Seeding creates the schema, the eight ZMB categories, an admin account and one
worked example guide. It is idempotent, so it is safe on every deploy, and it
never resets a password an operator has already changed. It **refuses** to run
without `RETICLE_ADMIN_PASSWORD` rather than falling back to a known default.

## Running

```powershell
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Add `--reload` while developing. Interactive docs are at `/docs`.

Behind a reverse proxy, terminate TLS there, keep `RETICLE_COOKIE_SECURE=true`,
and set `RETICLE_TRUST_FORWARDED_FOR=true` only if the proxy rewrites the
header. Run a single uvicorn worker or move `RETICLE_DATABASE_URL` to
PostgreSQL first — SQLite serialises writers, which is fine for one institute's
editing load but not for a worker pool.

## Tests

```powershell
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m pytest
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m pytest --cov=app --cov-report=term-missing
```

Each test gets a private in-memory database and a private media directory, so
the suite is order-independent even though sessions, the login throttle and
uploaded files are all persistent state. The environment variables the tests
need are set at the top of `tests/conftest.py`; no `.env` is required to run
them.

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
| `app/documents.py` | The whole-guide `PUT`: renumbering, media cap, concurrency. |
| `app/images.py` | Upload decoding, EXIF stripping, safe storage paths. |
| `app/audit.py` | The who-changed-what trail. |
| `app/seed.py` | First-run data. |
| `app/routers/` | One module per resource in the contract. |

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
  Accepted formats are PNG, JPEG, WebP and GIF; the file is re-encoded, which
  strips EXIF, and stored under a generated ULID path so a hostile filename
  cannot traverse.
- **Authorisation** is a dependency on every route.
  `test_every_api_route_is_behind_authentication` fails if a new route is added
  without one.

## Deviations from the contract

Recorded here rather than silently absorbed:

1. **`User` has no readable active flag.** `PATCH /api/users/{id}` is specified
   to change "active flag", but `User` in `types.ts` has no `isActive` field, so
   an admin can set it and never see it. The flag is implemented and enforced —
   deactivation blocks login and revokes live sessions — but the response stays
   field-for-field identical to `types.ts`. Adding `isActive: boolean` to `User`
   is a one-line contract change on both sides.
2. **`slug`, `status` and `version` are read-only in `PUT /api/guides/{id}`.**
   The editor round-trips the whole guide object, so these arrive in the body;
   they are ignored. Status moves through publish/unpublish only, and a mutable
   slug would break every link a ZMB guide is cited by.
3. **`publishedBy` is a `UserRef` object**, not a bare id. The contract writes
   `{version, publishedAt, publishedBy}` without saying which; an object matches
   how every other user reference in the model is shaped.
4. **No separate draft revision of a published guide.** `types.ts` says authors
   "work on a draft revision so the live version never breaks mid-edit", but the
   endpoint list has nothing to create, read or promote such a revision. Editing
   is therefore in place, and `GuideRevision` is immutable publish history —
   which is exactly what `POST /publish` and `GET /revisions/{version}` describe.
   Implementing the parallel-draft model needs new endpoints and a contract
   change; doing half of it would let a reader see a new title in a listing and
   the old one on the page.
5. **`GET /api/guides` excludes archived guides** unless `status=archived` is
   asked for explicitly. Archiving is a soft delete, so a default listing that
   still contained the archived guides would make the delete look broken.

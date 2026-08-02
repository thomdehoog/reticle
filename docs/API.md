# Reticle HTTP API contract

This is the agreed interface between `frontend/` and `backend/`. Both sides are
written against this document; changing it means changing both.

## Conventions

- Base path `/api`. JSON in, JSON out, UTF-8.
- **All field names are camelCase on the wire.** The backend serialises its
  snake_case columns to camelCase so the UI never translates.
- Timestamps are ISO-8601 UTC with a trailing `Z`.
- IDs are opaque strings (ULIDs). Clients must not parse them.
- Errors return
  `{"error": {"code": "<machine_code>", "message": "<human>"}, "requestId": "<id>"}`
  with a conventional status. Codes used: `invalid_credentials`,
  `not_authenticated`, `forbidden`, `not_found`, `validation_failed`,
  `conflict`, `rate_limited`, `payload_too_large`, `internal_error`.
  Nothing else appears in the body — in particular there is no `detail` key,
  because that is FastAPI's own shape and it leaks the raw validation structure.
- **Every response carries `X-Request-ID`**, and every error repeats it in the
  body as `requestId`. It is the same value the server writes into its log
  lines, so a user quoting the id from an error on screen turns "it broke this
  morning" into one findable request. A client may supply its own in the request
  header; it is echoed back if it looks like an id — letters, digits, hyphen,
  underscore, 8 to 200 characters — and replaced otherwise, because the value
  ends up in log files.
- `internal_error` means something failed that nobody anticipated. The message
  is always the same sentence and never describes the failure, because the
  description could name a table, echo submitted input or quote a filesystem
  path. The `requestId` is how it gets diagnosed.

## Authentication

The **entire application is behind the login** — every endpoint except
`POST /api/auth/login` requires an authenticated session and returns 401
otherwise. There is no anonymous read access.

Sessions use an **httpOnly, Secure, SameSite=Lax cookie** (`reticle_session`),
not a token in JavaScript, so a script injection cannot exfiltrate it. Mutating
requests additionally require the `X-CSRF-Token` header, echoing the
non-httpOnly `reticle_csrf` cookie.

| Method | Path                | Purpose                                      |
| ------ | ------------------- | -------------------------------------------- |
| POST   | `/api/auth/login`   | `{email, password}` → sets cookies, returns `User`. Rate limited. |
| POST   | `/api/auth/logout`  | Invalidates the server-side session.         |
| GET    | `/api/auth/me`      | Current `User`, or 401.                      |

### Roles

| Role     | Can                                                          |
| -------- | ------------------------------------------------------------ |
| `viewer` | Read published guides.                                        |
| `author` | Everything a viewer can, plus create/edit/publish guides.      |
| `admin`  | Everything, plus manage users and categories.                  |

Authorisation is enforced server-side on every endpoint. The frontend hides
controls a role cannot use, but that is cosmetic, never the check.

## Categories

| Method | Path                        | Role   | Purpose                     |
| ------ | --------------------------- | ------ | --------------------------- |
| GET    | `/api/categories`           | any    | Flat array of `Category`; the client builds the tree from `parentId`. |
| POST   | `/api/categories`           | admin  | Create.                     |
| PATCH  | `/api/categories/{id}`      | admin  | Rename, re-parent, reorder, hide. |
| DELETE | `/api/categories/{id}`      | admin  | 409 `conflict` if it still holds guides, pages or children. |
| GET    | `/api/categories/{id}/page` | any    | The category's landing `Page`, or `null` when nobody has written one. |

`Category` carries `heroMediaId` and the `imageUrl` derived from it. Browsing is
visual — a reader recognises the instrument before they finish reading its name
— so a section without a picture is shown with a figure drawn from its own name
rather than with a blank. `GuideSummary` carries `thumbnailUrl`, taken from the
guide's first step image, and `PageSummary` carries `heroImageUrl`.

`isHidden` marks a **holding category**: one that exists to own guides reached
through tags rather than by browsing. The client leaves them out of the tree.
They are not a permission — a hidden category's published guides are readable by
anyone who follows a tag or a link to them.

## Guides

| Method | Path                          | Role   | Purpose                    |
| ------ | ----------------------------- | ------ | -------------------------- |
| GET    | `/api/guides`                 | any    | Array of `GuideSummary`. Query: `categoryId`, `status`, `q`, `authorId`, `tags`. Viewers only ever receive `published`. |
| GET    | `/api/guides/{idOrSlug}`      | any    | Full `Guide` including `steps`. |
| POST   | `/api/guides`                 | author | Create a draft. Body: `{title, categoryId}`; everything else defaults. |
| PUT    | `/api/guides/{id}`            | author | Save the whole guide including steps, bullets and media order. Used by autosave. |
| POST   | `/api/guides/{id}/publish`    | author | Draft → published, `version` increments, snapshot written to history. |
| POST   | `/api/guides/{id}/unpublish`  | author | Published → draft; the guide stops resolving for viewers. |
| DELETE | `/api/guides/{id}`            | admin  | Archive (soft delete). Content is retained.  |
| GET    | `/api/guides/{id}/revisions`  | author | Publish history: `{version, publishedAt, publishedBy}`. |
| GET    | `/api/guides/{id}/revisions/{version}` | author | A past `Guide` snapshot. |

`PUT /api/guides/{id}` takes the full guide document — steps, bullets, media
order, annotations, tags and the video slot. The server renumbers `orderIndex`
contiguously from 0, rejects a step with more than `MAX_MEDIA_PER_STEP` (4)
images, rejects unknown media IDs, and rejects an image used as a video or a
video used as an image. This whole-document write is what lets the editor
autosave without a per-field endpoint zoo, and it makes reordering a plain array
move on the client.

`tags` is an array of slugs matching `^[a-z0-9]+(?:-[a-z0-9]+)*$`. The server
creates any tag that does not exist yet, and **refuses** a value in another
shape rather than re-slugifying it: silently rewriting a tag is how one
instrument ends up with four spellings that agree on screen and differ in the
database.

`?tags=a,b` requires a guide to carry **all** of the listed tags, up to 20 of
them. A wiki page asking for `stellaris, confocal` means the guides that are
both; `any` would turn every embed on the busiest page into an undifferentiated
dump.

`timeRequiredMinMinutes` and `timeRequiredMaxMinutes` are a range, because that
is how long a procedure honestly takes. A reversed pair is rejected rather than
swapped — the author meant one of the two numbers to be something else, and
guessing which would publish a time nobody wrote.

`contributors` is everyone who has **saved** the guide, in the order they first
touched it. Publishing is not saving: an administrator who releases a
colleague's guide has not written a word of it, and the by-line is permanent. `viewCount` increments when a **published** guide is read, and that
write deliberately does not move `updatedAt`: a read is not an edit, and moving
the concurrency token would eject every editor who had the guide open.

### Concurrency

`PUT` carries the `updatedAt` the client last saw. If the stored `updatedAt` is
newer, the server returns 409 `conflict` rather than silently overwriting a
colleague's edit — several ZMB staff may open the same guide.

## Wiki pages

A category's landing content is a `Page` with `isLanding` set, rather than a
body field on `Category`. That way pages, category landings, drafts, publishing
and version history are one mechanism instead of two — and it matches how the
material is actually organised, where a category page is a wiki page whose body
embeds tag-filtered guide lists.

| Method | Path                         | Role   | Purpose                    |
| ------ | ---------------------------- | ------ | -------------------------- |
| GET    | `/api/pages`                 | any    | Array of `PageSummary`. Query: `categoryId`, `status`, `q`. |
| GET    | `/api/pages/{idOrSlug}`      | any    | Full `Page`.               |
| POST   | `/api/pages`                 | author | Create a draft. Body: `{title, categoryId?, isLanding?}`. |
| PUT    | `/api/pages/{id}`            | author | Save the whole page. Same `updatedAt` concurrency rule as guides. |
| POST   | `/api/pages/{id}/publish`    | author | Draft → published, version increments, snapshot written. |
| POST   | `/api/pages/{id}/unpublish`  | author | Published → draft.         |
| DELETE | `/api/pages/{id}`            | admin  | Archive (soft delete).     |
| GET    | `/api/pages/{id}/revisions`  | author | Publish history.           |
| GET    | `/api/pages/{id}/revisions/{version}` | author | A past `Page` snapshot. |

A category may have at most one landing page; a second returns 409 `conflict`. A
page with `isLanding` and no `categoryId` is rejected.

## Tags and search

| Method | Path           | Role | Purpose                                        |
| ------ | -------------- | ---- | ---------------------------------------------- |
| GET    | `/api/tags`    | any  | Every tag with a `guideCount`, ordered by slug. |
| GET    | `/api/search`  | any  | `?q=` across guides and wiki pages.             |

`GET /api/tags` counts only guides the caller may see and omits a tag whose
whole membership is invisible to them — following it would land on an empty page
and look like a broken link.

`GET /api/search` returns a mixed array; each element is
`{"kind": "guide", "guide": GuideSummary}` or `{"kind": "page", "page":
PageSummary}`. A reader looking for "immersion oil" does not know whether the
answer was written as a guide or as a wiki page. Capped at 100 of each type.

## Media

| Method | Path                | Role   | Purpose                              |
| ------ | ------------------- | ------ | ------------------------------------ |
| POST   | `/api/media`        | author | `multipart/form-data` upload, one image or video. Returns `Media`. |
| GET    | `/api/media/{id}`   | any    | The bytes. Authenticated like everything else, and additionally refused to a viewer unless a published guide or page actually shows the file. |

Image uploads are validated by decoding the image, not by trusting the filename
or declared MIME type, and are re-encoded — which is what strips camera EXIF.
Accepted: PNG, JPEG, WebP, GIF. Limits: 20 MB, 10000 px per side, and a
pixel-product cap so that a small file cannot decode into a very large bitmap.

Videos are identified from their own header bytes (MP4 `ftyp` with a known
brand, or WebM's EBML magic) under a separate, larger size cap. They are not
re-encoded: that would mean shipping ffmpeg onto locked-down workstations for no
security gain, since the bytes are served back with a fixed `Content-Type` and
`nosniff` either way.

Files are stored outside the web root under a generated name, so a hostile
filename cannot traverse or execute.

### Annotations

An image carries `annotations`: shapes drawn over it, saved and replaced through
the whole-document guide write. Coordinates are fractions of the image (0..1) so
they survive being rendered at any size, and the colour comes from the same
eight-colour palette as bullets. That pairing is the point — a red shape on the
picture and the red bullet beside it are one instruction.

## Users

| Method | Path               | Role  | Purpose                                  |
| ------ | ------------------ | ----- | ---------------------------------------- |
| GET    | `/api/users`       | admin | List.                                     |
| POST   | `/api/users`       | admin | Create with a role and an initial password. |
| PATCH  | `/api/users/{id}`  | admin | Change role, display name, active flag.   |
| POST   | `/api/users/{id}/password` | self or admin | Change password. |

## Export

| Method | Path                  | Role  | Purpose                                  |
| ------ | --------------------- | ----- | ---------------------------------------- |
| GET    | `/api/export`         | admin | The whole corpus as JSON, without file bytes. |
| GET    | `/api/export/archive` | admin | The same document plus every image and video, streamed as `.tar.gz`. |

Both are audited. This is the entire institute's documentation in one request,
which makes it the most useful thing here to somebody who should not have it.

Guides and pages appear in exactly the shapes this document already describes,
so the export has no second contract to drift from. The format, and how to read
it without Reticle, is `EXPORT.md`. `python -m app.portability` does the same
job from the command line and can restore an export into an empty database —
which is what makes the format a promise rather than a claim.

## Rate limiting

Two separate mechanisms. Both answer 429 `rate_limited` with a `Retry-After`
header giving whole seconds.

**The login throttle** is backed by a table, so it survives a restart, and it
counts per (account, source address), per account and per source address.

**Everything else** is a per-minute ceiling held in memory, applied to every
endpoint except the two probes and the login. There are three independent
allowances so that exhausting one does not close the others — a reader who has
hit the read ceiling must still be able to sign out:

| Bucket   | Applies to                | Default per minute |
| -------- | ------------------------- | ------------------ |
| `read`   | GET, HEAD, OPTIONS        | 600                |
| `write`  | every other method        | 240                |
| `upload` | non-GET on `/api/media`   | 60                 |

Counted per source address, not per session: the session cookie is not checked
against the database until much later, so a caller could mint a fresh one on
every request and never be limited at all. The numbers are set where a person
cannot reach them and a loop can — an author saving every few seconds, a reader
opening thirty guides and an importer pushing a corpus all pass untouched.

The ceiling is **per process**. Two workers give twice the configured rate, and
a restart forgets everything. That is deliberate at this size; it is a brake on
a runaway script, not a security boundary.

A body larger than the limit is refused with 413 `payload_too_large` before
anything reads it: 2 MB for JSON, and a larger ceiling on `POST /api/media`
alone, sized above the video cap. That larger ceiling belongs to the route
rather than to the `Content-Type`, so a request cannot claim it by saying it is
an upload.

## Schema changes

Migrations are Alembic, in `backend/migrations/`, and they run on start-up, so a
deployment that forgets the migration step does not quietly serve traffic
against last release's schema. Three states are handled: an empty database
migrates from the beginning, a database predating migrations is stamped at the
current revision, and an already-stamped one runs whatever is pending. See
`app/db.py:init_db`; `deploy/migrate-all.sh` is the multi-facility equivalent.

A **destructive** migration should not run itself on start-up. When one is
written, run it deliberately and take a backup first — `MAINTENANCE.md`.

## Probes and public configuration

Three endpoints answer without a session. They are the whole of the
unauthenticated surface, and `app/main.PUBLIC_PATHS` is the list a test asserts
against.

| Method | Path          | Purpose                                            |
| ------ | ------------- | -------------------------------------------------- |
| GET    | `/api/health` | Liveness → `{"status": "ok"}`. Touches nothing.    |
| GET    | `/api/ready`  | Readiness → `{"status": "ready"}`, or 503 with `{"status": "starting"}` or `{"status": "database_unavailable"}`. |
| GET    | `/api/config` | `{"organisation": {"name", "shortName", "url"}}`.  |

Liveness and readiness are different questions on purpose. A liveness probe that
checked the database would turn a database blip into a restart loop — every
instance killed for a fault none of them can fix by restarting. A readiness
probe that did not check it would send requests to an instance that cannot
answer them. `/api/ready` also reports not-ready while start-up migrations are
running. Both probes are exempt from rate limiting, because an orchestrator
polls them by design.

`/api/ready` discloses one status word and nothing else: no error text, no
driver message, no URL. It should still be bound to an internal interface where
the deployment allows it.

`/api/config` is reachable without a session because the login screen has to say
which facility it belongs to, and it discloses nothing the hostname pointing at
the server does not already give away.

## Client error reports

| Method | Path                 | Role | Purpose                                   |
| ------ | -------------------- | ---- | ----------------------------------------- |
| POST   | `/api/client-errors` | any  | `{message, componentStack?, url?}` → 204. |

Where a browser-side crash goes. The frontend's error boundary posts here so a
render failure reaches the same log stream as everything else, with a request
id, instead of sitting in one person's devtools.

Deliberately not "whatever the client wants to send": three bounded fields, and
no user text, form values or local storage — a crash report that scoops up the
surrounding state eventually contains a password somebody was typing. `message`
is capped at 500 characters, `componentStack` at 4000 and `url` at 500, and both
sides truncate. Newlines are collapsed before anything is written, so a report
cannot forge the log entries around it. It sits behind the login and inside the
write allowance, so it cannot be used to fill a disk.

## Generated documentation

`/docs`, `/redoc` and `/openapi.json` are served **only** when `RETICLE_DEBUG`
is set. On a deployed instance they published the full route inventory and every
field name to anyone who asked, unauthenticated.

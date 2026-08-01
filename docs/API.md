# Reticle HTTP API contract

This is the agreed interface between `frontend/` and `backend/`. Both sides are
written against this document; changing it means changing both.

## Conventions

- Base path `/api`. JSON in, JSON out, UTF-8.
- **All field names are camelCase on the wire.** The backend serialises its
  snake_case columns to camelCase so the UI never translates.
- Timestamps are ISO-8601 UTC with a trailing `Z`.
- IDs are opaque strings (ULIDs). Clients must not parse them.
- Errors return `{"error": {"code": "<machine_code>", "message": "<human>"}}`
  with a conventional status. Codes used: `invalid_credentials`,
  `not_authenticated`, `forbidden`, `not_found`, `validation_failed`,
  `conflict`, `rate_limited`, `payload_too_large`.

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

`contributors` is everyone who has saved the guide, in the order they first
touched it. `viewCount` increments when a **published** guide is read, and that
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

## Schema changes

`create_all` adds tables that do not exist; it never alters one that does. A
release that adds a column therefore needs either a fresh database or the
`ALTER TABLE` run by hand — there is no migration tool here, deliberately, for
an installation that has one operator and reboots twice a year. `DEPLOYMENT.md`
says which release needs which.

## Health

`GET /api/health` → `{"status": "ok"}`. Unauthenticated, for uptime checks. It
reveals nothing beyond liveness.

`/docs`, `/redoc` and `/openapi.json` are served **only** when `RETICLE_DEBUG`
is set. On a deployed instance they published the full route inventory and every
field name to anyone who asked, unauthenticated.

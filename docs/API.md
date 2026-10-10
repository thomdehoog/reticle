# Reticle HTTP API contract

This is the agreed interface between `frontend/` and `backend/`. Both sides are
written against this document; changing it means changing both. The object
shapes (`Guide`, `Page`, `Tag`, `Media`, …) are defined field by field in
`frontend/src/domain/types.ts`, which the backend's `schemas.py` mirrors.

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
- `message` is written for the person using the editor and is shown to them
  as it stands. A `validation_failed` message is one sentence per problem (at
  most five): `Title: must be at most 240 characters.` for a field, located the
  way an author counts (`Step 2, bullet 3, text: …`), or a plain sentence when
  the problem concerns the document as a whole (`The minimum time required
  must not exceed the maximum.`). It never repeats the submitted value. The
  wording is not part of the contract; branch on `code`.

## Authentication

The **entire application is behind the login** — every endpoint except
`POST /api/auth/login` and `GET /api/health` requires an authenticated session
and returns 401 otherwise. There is no anonymous read access.

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
| `viewer` | Read published guides and pages.                              |
| `author` | Everything a viewer can, plus create/edit/publish guides and pages. |
| `admin`  | Everything, plus manage users and categories, and archive content. |

Authorisation is enforced server-side on every endpoint. The frontend hides
controls a role cannot use, but that is cosmetic, never the check.

### Visibility

One rule, applied everywhere content or a reference to content is returned
(listings, single reads, search, tag counts, media bytes, PDF):

- a **viewer** sees only `published` content;
- an **author** or **admin** sees everything except `archived`;
- anything else answers `404 not_found`, never 403, so a draft's existence is
  not disclosed.

## Categories

| Method | Path                         | Role   | Purpose                          |
| ------ | ---------------------------- | ------ | -------------------------------- |
| GET    | `/api/categories`            | any    | Flat array of `Category`; the client builds the tree from `parentId`. |
| POST   | `/api/categories`            | admin  | Create. Body: `{name, description?, parentId?, isHidden?}`. |
| PATCH  | `/api/categories/{id}`       | admin  | Rename, re-parent, reorder, hide. |
| DELETE | `/api/categories/{id}`       | admin  | 409 `conflict` if it still holds guides, pages or children. |
| GET    | `/api/categories/{id}/page`  | any    | The category's landing `Page`, or JSON `null` (status 200) when none is visible to the caller. |

`isHidden` marks a holding category: it owns guides that are reached through
tags, and the frontend leaves it out of the browsable tree. It is a navigation
hint, not an access control — its guides are still listed, searched and read
like any others.

## Tags

Tags are the navigation. A guide sits in exactly one category and carries any
number of tags; wiki pages embed tag-filtered guide lists.

| Method | Path         | Role | Purpose |
| ------ | ------------ | ---- | ------- |
| GET    | `/api/tags`  | any  | Array of `Tag` `{id, slug, name, guideCount}`, sorted by name. `guideCount` counts guides visible to the caller; tags with a count of 0 are omitted. |

Tags have no create or delete endpoint. Saving a guide with a tag that does not
exist creates it; a tag that no guide carries any more simply stops being
listed. On input a tag is trimmed, and its slug is the lower-case, hyphenated
form of the text with accents folded to plain letters (`"LAS X"` → `las-x`,
`"Präparation"` → `praeparation`: ä, ö, ü and ß become ae, oe, ue and ss, other
accents are dropped); the first spelling seen becomes the display `name`. A guide may carry at most 30 tags of at most 60 characters.
`Guide.tags` and `GuideSummary.tags` are arrays of **slugs**, sorted.

## Guides

| Method | Path                          | Role   | Purpose                    |
| ------ | ----------------------------- | ------ | -------------------------- |
| GET    | `/api/guides`                 | any    | Array of `GuideSummary`, newest `updatedAt` first. Query: `categoryId`, `status`, `q`, `authorId`, `tags`. |
| GET    | `/api/guides/{idOrSlug}`      | any    | Full `Guide` including `steps`. |
| POST   | `/api/guides`                 | author | Create a draft. Body: `{title, categoryId}`; everything else defaults. |
| PUT    | `/api/guides/{id}`            | author | Save the whole guide including steps, bullets, media order and annotations. Used by autosave. |
| POST   | `/api/guides/{id}/publish`    | author | Draft → published, `version` increments, snapshot written to history. |
| POST   | `/api/guides/{id}/unpublish`  | author | Published → draft; the guide stops resolving for viewers. |
| POST   | `/api/guides/{id}/view`       | any    | Records one read; `204`. Called once by the reader page, so editing a guide does not inflate `viewCount`. |
| DELETE | `/api/guides/{id}`            | admin  | Archive (soft delete). Content is retained.  |
| GET    | `/api/guides/{id}/revisions`  | author | Publish history: `{version, publishedAt, publishedBy}`. |
| GET    | `/api/guides/{id}/revisions/{version}` | author | A past `Guide` snapshot. |
| GET    | `/api/guides/{idOrSlug}/pdf`  | any    | The guide as a printable PDF (`application/pdf`, `Content-Disposition: attachment; filename="<slug>.pdf"`). |

`tags` on the listing is a comma-separated list of tag slugs; a guide must carry
**all** of them to match. `q` matches title, summary and tag names,
case-insensitively.

`PUT /api/guides/{id}` takes the full guide document. The server renumbers
`orderIndex` contiguously from 0, rejects a step with more than
`MAX_MEDIA_PER_STEP` (3) media, and rejects unknown media IDs. Server-owned
fields in the body (`author`, `viewCount`, `contributors`, `version`, …) are
ignored. The saving user is added to `contributors`. This whole-document write
is what lets the editor autosave without a per-field endpoint zoo, and it makes
reordering a plain array move on the client.

Field rules the server enforces:

- `difficulty` is one of `very_easy`, `easy`, `moderate`, `difficult`,
  `very_difficult`.
- `timeRequiredMinMinutes` / `timeRequiredMaxMinutes` are each `null` or an
  integer ≥ 0; when both are set, min ≤ max.
- Bullet `color` is one of `black`, `red`, `orange`, `yellow`, `green`,
  `light_blue`, `blue`, `violet`; `icon` is `null`, `note`, `caution` or
  `reminder`; `level` is 0, 1 or 2.
- Each media entry in a step is `{id, alt, annotations}`. An annotation is
  `{id, shape, color, x, y, width, height}` with `shape` one of `rectangle`,
  `ellipse`, `arrow`, `color` a bullet colour, and the four numbers fractions of
  the image: `x`, `y` in 0..1, `width`, `height` in -1..1 (an arrow may point
  up or left). At most 50 per image. Annotations belong to the image *within
  that step*, so the same upload reused elsewhere starts clean. Video media
  carries no annotations.
- Publishing requires a title, at least one step, and no step that has neither
  a bullet with text nor media; the `validation_failed` message names the
  offending step.

### Concurrency

`PUT` carries `expectedUpdatedAt`, the `updatedAt` the client last saw. If the
stored `updatedAt` differs, the server returns 409 `conflict` rather than
silently overwriting a colleague's edit — several ZMB staff may open the same
guide. `expectedUpdatedAt` is mandatory; omitting it is `validation_failed`.
Pages work the same way.

## Pages (the wiki)

A `Page` is long-form Markdown. A category's landing content is a page with
`isLanding: true` and that `categoryId`, so wiki pages, category pages, drafts,
publishing and history are one mechanism.

| Method | Path                          | Role   | Purpose                    |
| ------ | ----------------------------- | ------ | -------------------------- |
| GET    | `/api/pages`                  | any    | Array of `PageSummary`, by title. Query: `categoryId`, `status`, `q`. |
| GET    | `/api/pages/{idOrSlug}`       | any    | Full `Page`. |
| POST   | `/api/pages`                  | author | Create a draft. Body: `{title, categoryId?, isLanding?}`. |
| PUT    | `/api/pages/{id}`             | author | Save the whole page; carries `expectedUpdatedAt`. |
| POST   | `/api/pages/{id}/publish`     | author | Draft → published, `version` increments, snapshot written. Requires a title and a non-empty body. |
| POST   | `/api/pages/{id}/unpublish`   | author | Published → draft. |
| POST   | `/api/pages/{id}/view`        | any    | Records one read; `204`. |
| DELETE | `/api/pages/{id}`             | admin  | Archive (soft delete). |
| GET    | `/api/pages/{id}/revisions`   | author | Publish history. |
| GET    | `/api/pages/{id}/revisions/{version}` | author | A past `Page` snapshot. |

Rules:

- `isLanding: true` requires a `categoryId`, and a category has at most one
  non-archived landing page; a second is 409 `conflict`.
- `heroMediaId`, when set, must be an existing image.
- `heroAlt` is the text alternative for that image: a string of at most 1000
  characters, `""` by default, trimmed on save. It is stored only alongside a
  hero — saving with `heroMediaId: null` resets it to `""` — and it is part of
  the published snapshot. Snapshots written before the field existed do not
  carry it; read a missing `heroAlt` as `""`.
- `body` is at most 200 000 characters. It is stored and returned verbatim; the
  frontend renders it to React elements and ignores raw HTML.
- Images are placed in a body as ordinary Markdown, `![alt](/api/media/<id>)`.
  The server records those references on save, which is what makes the image
  readable by viewers once the page is published.
- A fenced block with the info string `guidelist` embeds a tag-filtered guide
  list. The server does not interpret it; the frontend turns it into
  `GET /api/guides?tags=…`.

## Search

`GET /api/search?q=<term>` → array of `SearchResult`, each either
`{"kind": "guide", "guide": GuideSummary}` or `{"kind": "page", "page":
PageSummary}`. Guides match on title, summary, tag names, step titles and bullet
text; pages on title, summary and body. Title matches rank first. At most 50
results. An empty or whitespace `q` returns `[]`. Visibility applies.

## Media

| Method | Path                | Role   | Purpose                              |
| ------ | ------------------- | ------ | ------------------------------------ |
| POST   | `/api/media`        | author | `multipart/form-data` upload, one file in field `file`, optional `alt`. Returns `Media`. |
| GET    | `/api/media/{id}`   | any    | The bytes. Authenticated like everything else; honours `Range`, which is what lets a video seek. |

`Media` is `{id, kind, url, alt, width, height, annotations}` where `kind` is
`image` or `video`.

**Images** are validated by decoding, not by trusting the filename or declared
MIME type. Accepted: PNG, JPEG, WebP, GIF. Limits: 20 MB
(`RETICLE_MAX_UPLOAD_BYTES`), 10000 px per side, and a cap on total pixels
checked *before* decode so a small file cannot expand into gigabytes of memory.
Images are re-encoded, which removes EXIF; the EXIF orientation is applied to
the pixels first, so a photo taken in portrait is stored upright and
`width`/`height` describe it as displayed. The limits in force are published
at `GET /api/config`.

**Videos** are accepted as MP4 (H.264/AAC is what every browser plays) and
WebM, identified by container signature. Limit: 200 MB
(`RETICLE_MAX_VIDEO_BYTES`). They are stored as uploaded — the server does not
transcode — and `width`/`height` are `null`.

Files are stored outside the web root under a generated name, so a hostile
filename cannot traverse or execute. Responses carry
`X-Content-Type-Options: nosniff`.

A viewer can fetch a media item only while it is referenced by something they
can read: a step of a published guide, or the hero or body of a published page.
Authors can fetch any media.

## Configuration

| Method | Path          | Role | Purpose |
| ------ | ------------- | ---- | ------- |
| GET    | `/api/config` | any  | `{maxImageBytes, maxVideoBytes, maxMediaPerStep}`: the limits this server enforces. |

The limits are the operator's (`RETICLE_MAX_UPLOAD_BYTES`,
`RETICLE_MAX_VIDEO_BYTES`, `RETICLE_MAX_MEDIA_PER_STEP`), so a client reads
them here instead of assuming the defaults — 20 MB, 200 MB and 3 — and uses
them to refuse an oversized file before uploading it. They are advisory to the
client only: the server enforces every one of them itself. Nothing else about
the configuration is exposed.

## Users

| Method | Path               | Role  | Purpose                                  |
| ------ | ------------------ | ----- | ---------------------------------------- |
| GET    | `/api/users`       | admin | List.                                     |
| POST   | `/api/users`       | admin | Create with a role and an initial password. |
| PATCH  | `/api/users/{id}`  | admin | Change role, display name, active flag.   |
| POST   | `/api/users/{id}/password` | self or admin | Change password. |

## Health

`GET /api/health` → `{"status": "ok"}` once the database answers a trivial
query, `503` otherwise. Unauthenticated, for uptime checks and the container
healthcheck. It reveals nothing beyond liveness.

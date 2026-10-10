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
  `conflict`, `rate_limited`, `payload_too_large`, and `internal_error` (500)
  for a failure that is the server's own — its message is always the same and
  says nothing about what went wrong. A `rate_limited` (429) response from
  anything other than the login carries a `Retry-After` header in seconds.
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

### Cookies

| Cookie            | Attributes | Purpose |
| ----------------- | ---------- | ------- |
| `reticle_session` | httpOnly, Secure, SameSite=Lax, path `/`, 12 h | The session. An opaque token; the server keeps only a keyed digest of it. Cleared at logout. |
| `reticle_csrf`    | Secure, SameSite=Lax, path `/`, 12 h, readable by script | Echoed in `X-CSRF-Token` on mutating requests. Cleared at logout. |
| `reticle_device`  | httpOnly, Secure, SameSite=Lax, path `/api/auth`, 180 days | Marks this browser as one that has signed in to this account before. Read only by the login throttle. Deliberately kept at logout. |

`reticle_device` grants no access and identifies nothing by itself: it is
`v2.<nonce>.<issued-at>.<signature>`, a keyed signature over the nonce, the
issue time, the account's address and the account's **credential epoch**.
There is no server-side record of it. It stops verifying when it is older than
180 days, and when the account's password is changed, reset by an
administrator, or the account is deactivated — each of those raises the epoch
(and revokes the account's sessions; a self-service password change keeps the
session that made it and re-issues that browser's cookie). A browser in
regular use gets a fresh one at sign-in once its cookie is 30 days old. A
client never needs to read or send it deliberately; a browser does both.

### Login throttling

Failed sign-ins are counted in a 15-minute window, and a request over a limit
is answered `429 rate_limited` *before* any password is checked. The response
to a wrong password and to an unknown or deactivated account is the same, and
costs the server the same.

| Counter | Limit | Applies to |
| ------- | ----- | ---------- |
| per account and source address | 5 | browsers without a valid `reticle_device` for the account |
| per source address (an IPv6 source is its /64) | 20 | the same |
| per account | 50 | the same |
| per device cookie | 5 | a browser with a valid `reticle_device` for the account |
| per account, over all its device cookies | 50 | the same |

What the device cookie buys is exactly this: a browser that has signed in to
the account before is **not turned away by counters other people can fill** —
the noise of a shared address (a NAT, an instrument PC), or a guess at the
account spread over many hosts. It is held to the same five attempts as anyone,
all cookies of one account together are held to the account's ceiling, and its
attempts are still written to the per-account counter that everyone else is
measured against. A successful sign-in forgives that browser's own failures and
nothing else.

### Roles

| Role     | Can                                                          |
| -------- | ------------------------------------------------------------ |
| `viewer` | Read published guides and pages.                              |
| `author` | Everything a viewer can, plus create/edit/publish guides and pages. |
| `admin`  | Everything, plus manage users and categories, and archive content. |

Authorisation is enforced server-side on every endpoint. The frontend hides
controls a role cannot use, but that is cosmetic, never the check.

### Visibility

Two rules, applied everywhere content or a reference to content is returned
(listings, single reads, search, tag counts, landing pages, media bytes, PDF).

**Which items.**

- a **viewer** sees only `published` content;
- an **author** or **admin** sees everything except `archived`;
- anything else answers `404 not_found`, never 403, so a draft's existence is
  not disclosed.

**Which text of an item.** A guide or page exists twice. The **working copy**
is what the editor loads and autosaves into with `PUT`. The **published
snapshot** is the immutable document written by the last `publish`. Saving
changes the working copy only; nothing a reader is served changes until the
next publish.

- A **viewer is only ever served the published snapshot**, by every route:
  `GET` by id or by slug; the fields of `GuideSummary` / `PageSummary` in
  listings (title, summary, tags, category, difficulty, time, step count,
  `isLanding`); the `tags`, `q` and `categoryId` filters; tag counts; search,
  which neither matches nor returns unpublished text; a category's landing
  page; the PDF; and media bytes — a viewer may fetch a media item only if the
  published snapshot of some currently published guide or page shows it (a
  step, a page hero, a reference in a page body). An upload that exists only
  in an unpublished edit is `404` to a viewer.
- An **author or admin is served the working copy** by default, everywhere:
  single reads, listings, filters, tag counts, search and the PDF. That is what
  an author looks for a guide by. Authors can fetch any media.
- An author or admin can ask for exactly what readers get with
  **`?view=published`** on `GET /api/guides/{idOrSlug}`,
  `GET /api/pages/{idOrSlug}`, `GET /api/categories/{id}/page` and
  `GET /api/guides/{idOrSlug}/pdf`. It is `404` for an item that is not
  published at this moment — never published, or unpublished since — because
  readers are then being shown nothing. `?view=working` is the default spelt
  out. A viewer's `view` parameter is ignored. Listings, tags and search take
  no `view`.

`hasUnpublishedChanges` (on `Guide`, `Page`, `GuideSummary`, `PageSummary`)
is `true` when the item is `published` and its working copy reads differently
from its snapshot. "Differently" means in content: title, summary, category,
tags, difficulty, time, introduction, conclusion, steps, bullets, media, alt
text and annotations for a guide; title, summary, category, `isLanding`, body,
hero and `heroAlt` for a page. Identifiers, timestamps and view counts are not
content, so a save that restores the published text — including an autosave
that changed nothing — leaves it `false`. It is always `false` for a draft,
and **always `false` in anything served to a viewer**, including when it is
actually true: that there is newer work is itself not for readers.

In a published snapshot, `updatedAt` is the moment the snapshot was made,
`viewCount`, `slug` and `status` are the item's current ones, and every other
field is as it was published.

**Slugs do not change.** A guide's or page's `slug` is derived from the title
it is created with and is its address from then on: it is not recomputed when
the title is saved, nor when the item is published or republished. Links to
`/g/<slug>` and `/w/<slug>`, and `idOrSlug` in this API, keep resolving however
often something is renamed.

## Categories

| Method | Path                         | Role   | Purpose                          |
| ------ | ---------------------------- | ------ | -------------------------------- |
| GET    | `/api/categories`            | any    | Flat array of `Category`; the client builds the tree from `parentId`. |
| POST   | `/api/categories`            | admin  | Create. Body: `{name, description?, parentId?, isHidden?}`. |
| PATCH  | `/api/categories/{id}`       | admin  | Rename, re-parent, reorder, hide. |
| DELETE | `/api/categories/{id}`       | admin  | 409 `conflict` if it still holds guides, pages or children. |
| GET    | `/api/categories/{id}/page`  | any    | The category's landing `Page`, or JSON `null` (status 200) when none is visible to the caller. Takes `?view=published` like a page read. |

Deleting a category is also `409` while a published snapshot is still filed in
it — a guide or page whose move elsewhere has been saved but not published.
Which page is a category's landing page is content like the rest of a page:
for readers it is the snapshot's `categoryId` and `isLanding` that decide.

`isHidden` marks a holding category: it owns guides that are reached through
tags, and the frontend leaves it out of the browsable tree. It is a navigation
hint, not an access control — its guides are still listed, searched and read
like any others.

## Tags

Tags are the navigation. A guide sits in exactly one category and carries any
number of tags; wiki pages embed tag-filtered guide lists.

| Method | Path         | Role | Purpose |
| ------ | ------------ | ---- | ------- |
| GET    | `/api/tags`  | any  | Array of `Tag` `{id, slug, name, guideCount}`, sorted by name. `guideCount` counts guides visible to the caller; tags with a count of 0 are omitted. For a viewer the tags counted are those of the published snapshots; for an author, of the working copies. |

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
| GET    | `/api/guides/{idOrSlug}`      | any    | Full `Guide` including `steps`: the published snapshot for a viewer, the working copy for an author. Query: `view` (see Visibility). |
| POST   | `/api/guides`                 | author | Create a draft. Body: `{title, categoryId}`; everything else defaults. |
| PUT    | `/api/guides/{id}`            | author | Save the whole working copy including steps, bullets, media order and annotations. Used by autosave. Readers see no change. |
| POST   | `/api/guides/{id}/publish`    | author | The working copy becomes what readers see: status `published`, `version` increments, snapshot written to history. |
| POST   | `/api/guides/{id}/unpublish`  | author | Published → draft; the guide stops resolving for viewers. The working copy is kept. |
| POST   | `/api/guides/{id}/revert`     | author | Discard unpublished changes: the working copy is replaced by the published snapshot. Returns the `Guide`. `409 conflict` when the guide is not currently published. |
| POST   | `/api/guides/{id}/view`       | any    | Records one read; `204`. Called once by the reader page, so editing a guide does not inflate `viewCount`. Does not change `updatedAt` or `hasUnpublishedChanges`. |
| DELETE | `/api/guides/{id}`            | admin  | Archive (soft delete). Content is retained.  |
| GET    | `/api/guides/{id}/revisions`  | author | Publish history: `{version, publishedAt, publishedBy}`. |
| GET    | `/api/guides/{id}/revisions/{version}` | author | A past `Guide` snapshot. |
| GET    | `/api/guides/{idOrSlug}/pdf`  | any    | The guide as a printable PDF (`application/pdf`, `Content-Disposition: attachment; filename="<slug>.pdf"`). Query: `view`. See "PDF export". |

`tags` on the listing is a comma-separated list of tag slugs; a guide must carry
**all** of them to match. `q` matches title, summary and tag names,
case-insensitively. For a viewer every filter, and every field of the result,
is the published snapshot's; for an author, the working copy's. A viewer's
listing is ordered by when each guide was last published, an author's by when
it was last saved.

`POST /api/guides/{id}/revert` restores everything a snapshot holds — text,
tags, category, steps with their original identifiers, media, annotations —
moves `updatedAt` (an editor that still holds the discarded copy is refused as
stale), and leaves `version`, `status` and the history untouched. It takes no
body and no `expectedUpdatedAt`: it is a deliberate overwrite.

### PDF export

A viewer's PDF is the published snapshot. An author's is the working copy
unless `?view=published` is given.

- The export of a published version is rendered once and kept on disk; later
  requests for the same version are served from that file and are not limited.
  Working copies and drafts are rendered on each request and never kept.
- Rendering is rationed: two at a time per server process, and one at a time
  per signed-in user. A request that cannot start is answered **at once** with
  `429 rate_limited` and `Retry-After: 5`; nothing queues. A client should
  wait that long and ask again, and tell the person it is doing so.

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
- Identifiers a client supplies — for steps, bullets and annotations — must
  each be unique across the **whole document**, not merely within their step
  or image; a repeat is `validation_failed`. Step and bullet identifiers are
  ULIDs; omit an identifier and the server mints one.
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
| GET    | `/api/pages/{idOrSlug}`       | any    | Full `Page`: the published snapshot for a viewer, the working copy for an author. Query: `view`. |
| POST   | `/api/pages`                  | author | Create a draft. Body: `{title, categoryId?, isLanding?}`. |
| PUT    | `/api/pages/{id}`             | author | Save the whole working copy; carries `expectedUpdatedAt`. Readers see no change. |
| POST   | `/api/pages/{id}/publish`     | author | The working copy becomes what readers see; `version` increments, snapshot written. Requires a title and a non-empty body. |
| POST   | `/api/pages/{id}/unpublish`   | author | Published → draft. |
| POST   | `/api/pages/{id}/revert`      | author | Discard unpublished changes, as for a guide. `409` when the page is not currently published, or when restoring it would take a landing slot another page now holds. |
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
- Images are placed in a body as ordinary Markdown, `![alt](/api/media/<id>)`,
  optionally `/api/media/<id>?size=display` (see Media). The server records
  those references on save and again, from the snapshot, on publish; the
  published ones are what make an image readable by viewers.
- A fenced block with the info string `guidelist` embeds a tag-filtered guide
  list. The server does not interpret it; the frontend turns it into
  `GET /api/guides?tags=…`.

## Search

`GET /api/search?q=<term>` → array of `SearchResult`, each either
`{"kind": "guide", "guide": GuideSummary}` or `{"kind": "page", "page":
PageSummary}`. Guides match on title, summary, tag names, step titles and bullet
text; pages on title, summary and body. Title matches rank first. At most 50
results. An empty or whitespace `q` returns `[]`. Visibility applies in both
its halves: a viewer's term is matched against published snapshots only, so
text in an unpublished edit cannot be found, or confirmed to exist by being
found; an author's is matched against working copies.

## Media

| Method | Path                | Role   | Purpose                              |
| ------ | ------------------- | ------ | ------------------------------------ |
| POST   | `/api/media`        | author | `multipart/form-data` upload, one file in field `file`, optional `alt`. Returns `Media`. |
| GET    | `/api/media/{id}`   | any    | The bytes. Authenticated like everything else; honours `Range`, which is what lets a video seek. Query: `size=display`. `HEAD` is answered the same way, without the body. |
| DELETE | `/api/media/{id}`   | author | Remove an upload permanently. Query: `force=true` (admin). `204`. |

`Media` is `{id, kind, url, displayUrl, alt, width, height, annotations}` where
`kind` is `image` or `video`.

- `url` is the file as stored: use it for "open full size" and for zooming.
- `displayUrl` is what belongs in an `<img>`: for an image
  `/api/media/{id}?size=display`, a copy whose longer side is at most
  **2560 px**, in the original's format; for a video it equals `url`. An image
  already that small is served as itself, and so is an animation.
- `width` and `height` are the **original's**. They are the right aspect ratio
  for either file, which is what an `<img width height>` needs to reserve its
  space. Annotation coordinates are fractions of the image, so they apply
  unchanged to the display copy.

The display copy is made when the image is uploaded. For media that predates
it, or was stored by the importer, it is made the first time it is asked for;
if that cannot be done at that moment the original is served instead, so the
request never fails for want of a copy.

**Images** are validated by decoding, not by trusting the filename or declared
MIME type. Accepted: PNG, JPEG, WebP, GIF. Limits: 20 MB
(`RETICLE_MAX_UPLOAD_BYTES`), 10000 px per side, and a cap on total pixels
checked *before* decode so a small file cannot expand into gigabytes of memory.
The limits in force are published at `GET /api/config`.

What is stored depends on what the file contains:

- A PNG, JPEG or WebP that is **nothing but a picture** — pixel data, colour
  description and structure, and no byte after its end marker — is stored
  **exactly as uploaded**. A screenshot is not put through an encoder twice.
- Anything carrying more — EXIF, XMP, IPTC, comments, PNG text chunks, private
  chunks, trailing data — is **re-encoded**, which is what removes it. The EXIF
  orientation is applied to the pixels first, so a photo taken in portrait is
  stored upright and `width`/`height` describe it as displayed. PNG and
  lossless WebP stay lossless; JPEG is written at quality 92 with the source's
  chroma subsampling; lossy WebP at quality 92. An embedded colour profile is
  kept. GIFs are always re-encoded.

**Videos** are accepted as MP4 (H.264/AAC is what every browser plays) and
WebM, identified by container signature. Limit: 200 MB
(`RETICLE_MAX_VIDEO_BYTES`). They are stored as uploaded — the server does not
transcode — and `width`/`height` are `null`.

When the operator has set `RETICLE_MAX_MEDIA_STORE_BYTES`, an upload that would
take the stored originals past that total is refused with
`413 payload_too_large` before it is processed.

Files are stored outside the web root under a generated name, so a hostile
filename cannot traverse or execute. Responses carry
`X-Content-Type-Options: nosniff`.

**Caching.** Media responses carry `Cache-Control: private, no-cache` and a
strong `ETag`. A browser may keep the bytes but must ask before using them
again; a request with a matching `If-None-Match` is answered `304` with no
body — after the same login and visibility checks as a full response, so a
copy left in the cache of a shared PC is of no use to whoever sits down next.
The original and the display copy have different `ETag`s. `If-Range` accepts
the `ETag`.

A viewer can fetch a media item only while the published snapshot of a
currently published guide or page shows it (see Visibility). Authors can fetch
any media.

### Deleting

`DELETE /api/media/{id}` removes the row, the stored file and its display copy.

- **Who:** an administrator, or the author who uploaded the file. Anyone else
  is `403`.
- **What:** an upload that **nothing uses** — no step of any guide's working
  copy, no page hero, no page body, and no published snapshot of any version,
  past or present.
- An upload that is still used is refused with `409 conflict`; the message
  names where (up to five places).
- **`?force=true`, administrators only**, is for a file that must not exist:
  it is first taken out of every working copy (the step entry and its
  annotations; a page's hero and its `heroAlt`; in a page body an image
  reference is removed whole and any other occurrence of the address is
  blanked) and out of **every stored snapshot**, including the ones readers
  are being served and the history. Affected guides and pages get a new
  `updatedAt`, so an open editor is refused as stale rather than re-adding the
  file; cached PDF exports of affected guides are discarded. This is the one
  operation that rewrites published history, and it is recorded in the audit
  log with what it touched. Backups taken earlier still contain the file.

Uploads nobody deleted and nothing uses are collected by an operator command,
`python -m app.maintenance purge-orphans`; see `backend/README.md`.

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

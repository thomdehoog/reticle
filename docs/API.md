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

| Method | Path                   | Role   | Purpose                          |
| ------ | ---------------------- | ------ | -------------------------------- |
| GET    | `/api/categories`      | any    | Flat array of `Category`; the client builds the tree from `parentId`. |
| POST   | `/api/categories`      | admin  | Create.                          |
| PATCH  | `/api/categories/{id}` | admin  | Rename, re-parent, reorder.      |
| DELETE | `/api/categories/{id}` | admin  | 409 `conflict` if it still holds guides or children. |

## Guides

| Method | Path                          | Role   | Purpose                    |
| ------ | ----------------------------- | ------ | -------------------------- |
| GET    | `/api/guides`                 | any    | Array of `GuideSummary`. Query: `categoryId`, `status`, `q`, `authorId`. Viewers only ever receive `published`. |
| GET    | `/api/guides/{idOrSlug}`      | any    | Full `Guide` including `steps`. |
| POST   | `/api/guides`                 | author | Create a draft. Body: `{title, categoryId}`; everything else defaults. |
| PUT    | `/api/guides/{id}`            | author | Save the whole guide including steps, bullets and media order. Used by autosave. |
| POST   | `/api/guides/{id}/publish`    | author | Draft → published, `version` increments, snapshot written to history. |
| POST   | `/api/guides/{id}/unpublish`  | author | Published → draft; the guide stops resolving for viewers. |
| DELETE | `/api/guides/{id}`            | admin  | Archive (soft delete). Content is retained.  |
| GET    | `/api/guides/{id}/revisions`  | author | Publish history: `{version, publishedAt, publishedBy}`. |
| GET    | `/api/guides/{id}/revisions/{version}` | author | A past `Guide` snapshot. |

`PUT /api/guides/{id}` takes the full guide document. The server renumbers
`orderIndex` contiguously from 0, rejects a step with more than
`MAX_MEDIA_PER_STEP` (3) media, and rejects unknown media IDs. This whole-
document write is what lets the editor autosave without a per-field endpoint
zoo, and it makes reordering a plain array move on the client.

### Concurrency

`PUT` carries the `updatedAt` the client last saw. If the stored `updatedAt` is
newer, the server returns 409 `conflict` rather than silently overwriting a
colleague's edit — several ZMB staff may open the same guide.

## Media

| Method | Path                | Role   | Purpose                              |
| ------ | ------------------- | ------ | ------------------------------------ |
| POST   | `/api/media`        | author | `multipart/form-data` upload, one image. Returns `Media`. |
| GET    | `/api/media/{id}`   | any    | The image bytes. Authenticated like everything else. |

Uploads are validated by decoding the image, not by trusting the filename or
declared MIME type. Accepted: PNG, JPEG, WebP, GIF. Limits: 20 MB, 10000 px per
side. Files are stored outside the web root under a generated name, so a hostile
filename cannot traverse or execute.

## Users

| Method | Path               | Role  | Purpose                                  |
| ------ | ------------------ | ----- | ---------------------------------------- |
| GET    | `/api/users`       | admin | List.                                     |
| POST   | `/api/users`       | admin | Create with a role and an initial password. |
| PATCH  | `/api/users/{id}`  | admin | Change role, display name, active flag.   |
| POST   | `/api/users/{id}/password` | self or admin | Change password. |

## Health

`GET /api/health` → `{"status": "ok"}`. Unauthenticated, for uptime checks. It
reveals nothing beyond liveness.

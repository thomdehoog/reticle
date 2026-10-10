# Reticle — plan and progress

Working notes for picking this up again. Last updated 2026-10-10.

**Reticle** is a self-hosted replacement for ZMB's paid Dozuki subscription,
covering the two things ZMB actually uses: **guides** and **wikis**.

---

## Where it stands

The application is feature-complete against what the census of ZMB's live site
says is used, it is packaged to run on a server with Docker Compose, and the
importer that will carry the existing content across is written.

**It is not in production, and ZMB's content is not in it.** The importer has
never been run against the live site. That run is the one time-critical item
left — see "What is left".

| | as of 2026-10-10 |
| --- | --- |
| Backend tests | 960 passing, 99% branch coverage (the gate is 95%) |
| Frontend tests | 575 passing |
| Browser tests | smoke test at 1440 / 768 / 390 px and an authoring round-trip, both also run against the Docker stack under the production Content-Security-Policy |
| Deployment | two images, `compose.yaml`, backup / restore / upgrade scripts — exercised end to end, with the caveats under "Deployment: what was and was not verified" |

The test counts are a snapshot. UI polish and the importer are still being
worked on and will add to both suites; trust CI, not this table.

### Running it

`README.md` has both ways: the five-minute Docker trial with demo content, and
the two-process development setup (Linux/macOS first, the ZMB Windows and
AppLocker specifics in their own section). `docs/DEPLOYMENT.md` is the real
installation.

---

## The finding that shaped the design

A census of **all 257 publicly visible guides** on zmb.dozuki.com, via the
vendor API, produced one result that overrides intuition:

> **ZMB's navigation is not the category tree.** Category pages are wiki pages
> whose body contains tag-filtered guide lists. Guides live in deliberately
> hidden holding categories (`Confocal - hidden guides` holds 86) and surface
> through **tags** — 137 of them. A guide has one category and many tags, which
> is how one LAS X guide appears under ten instrument headings.

A replacement modelled as a browsable category tree cannot reproduce the site.
Tags and wiki-embedded guide lists are the navigation, not a nice-to-have.

Measured usage also corrected the model in both directions:

| Used heavily | Built but unused at ZMB |
| --- | --- |
| 8 bullet colours + note/caution/reminder, all 11 in service | Prerequisites — **0** of 257 guides |
| 3 images per step is the most common case | Conclusions — 2 of 257 |
| Indent levels 0/1/2 | |
| Colour-matched annotations drawn on step images | |
| Time as a **range** (`00:30 – 01:30`) | |
| Videos in steps — 90 steps across 25 guides | |
| PDF export | |

Safely ignorable, confirmed from the data: multilingual (English only;
`langid=de` returns 404), Answers/Q&A (one question ever, and ZMB hid the button
with custom CSS), comments and favourites (zero on a 6,745-view guide), quizzes,
courses, approvals, collections.

⚠️ That census covers the **anonymous** subset. Private guides exist and were not
inventoried. The importer's first authenticated run is also the first complete
inventory — read its report before dropping anything.

---

## Architecture

```
reticle/
├── docs/API.md          the contract — both halves are written against it
├── docs/DEPLOYMENT.md   Docker Compose install, TLS modes, upgrade, rollback
├── docs/MAINTENANCE.md  backups, restores, people, logs, troubleshooting
├── docs/IMPORT.md       carrying the existing content across
├── frontend/            React 19 + TypeScript + Vite + TanStack Query + TanStack Router
├── backend/             FastAPI + SQLAlchemy + SQLite + Alembic
├── compose.yaml         app (API) + web (Caddy), one data volume
└── deploy/              Caddyfile, image entrypoint, backup/restore/upgrade scripts
```

Decisions worth not re-litigating:

- **One data path.** A single typed HTTP client, no second "offline" adapter.
  Tests inject a fake transport, so the code under test is the code that ships.
- **Whole-document saves.** `PUT /api/guides/{id}` writes the entire guide. That
  is what makes autosave possible without a per-field endpoint per property, and
  reordering a plain array move. The write carries the `updatedAt` the editor
  last saw, so a colleague's concurrent save is refused rather than overwritten.
- **A category page is a wiki page.** `Page` with `isLanding` set, rather than a
  body field on `Category` — so pages, category landings, drafts, publishing and
  version history are one mechanism.
- **Markdown renders to React elements**, never to HTML. No `innerHTML`, no
  sanitiser to maintain, no stored-XSS vector from the editor — and it is what
  lets the production Content-Security-Policy do without `unsafe-inline`.
- **Annotations are data, not pixels.** Shapes with fractional coordinates over
  an untouched original, so they scale and stay editable.
- **Backend serves no static files; the proxy serves no media.** Caddy serves
  the built frontend and proxies `/api`. Same origin, so CORS does not apply.
  Uploads are reachable only through the API, per request, behind the login.
- **The schema is owned by migrations.** `python -m app.migrate` (Alembic) is a
  deliberate step and the server refuses to start on a schema it does not
  recognise. In the container that step runs before uvicorn, so an upgrade is
  "start the new image" — and a rollback across a migration needs the
  pre-upgrade backup, which `deploy/upgrade.sh` always takes.
- **Server state lives in TanStack Query, navigation in TanStack Router.** The
  hand-rolled fetching hooks and the hand-rolled router are gone.
- **Releases are images; servers pull.** A `v*` tag publishes two images to
  GHCR and a small deployment bundle. Nothing in CI can reach, or needs
  credentials for, a ZMB machine. The earlier SSH-and-symlink deploy workflow
  was retired for that reason.
- **SQLite, in WAL mode, on a local volume.** PostgreSQL is kept possible by
  the ORM and is untested.

---

## Done

- [x] Repo, MIT licence, `NOTICE.md` recording clean-room provenance
- [x] Domain model and pure editor logic, test-first
- [x] Typed API client, auth session, role gating
- [x] Login — the whole app is behind it; any URL falls back to the login screen
- [x] Browsing: categories, guide reader, breadcrumbs
- [x] **Authoring GUI**: step add/delete/reorder (drag *and* buttons), Enter for
      the next bullet, Backspace to remove an empty one, Tab to indent, colour
      and flag picker, drag-drop media into three per-step slots, autosave,
      publish with validation that names the offending step
- [x] People management, self-service password change
- [x] Responsive down to 360 px; hover-only controls made permanent on touch
- [x] **Tags end to end** — `Tag` model, `?tags=` filtering, tag input in the
      guide editor, tag index and `/t/:tag` listings, tags in search
- [x] **Wiki pages** — `Page` model and endpoints, viewer, editor with
      formatting toolbar and live preview, category landing pages,
      tag-filtered guide-list embeds
- [x] **Image annotations** — drawn over step images in the bullet's colour
- [x] **Step video** — MP4/WebM up to 200 MB, recognised by container
      signature, streamed to disk, served with `Range` so it seeks
- [x] **PDF export** of a guide (ReportLab; DejaVu fonts for λ, Å, ≥)
- [x] **Search** across guides and pages
- [x] **Version history** — every publish is an immutable snapshot, and old
      versions are readable
- [x] **Security review items, each fixed and pinned by a test** — see
      "Security"
- [x] **Migrations** — Alembic, `python -m app.migrate`, start-up schema check
- [x] **Frontend moved to TanStack Query and TanStack Router**
- [x] Contract (`docs/API.md`) covers all of the above; prerequisites removed
- [x] **Docker deployment** — non-root, read-only images; `compose.yaml` with
      Caddy in front; three TLS modes (Let's Encrypt, certificate files from
      IT, internal CA) plus plain http for a localhost trial or behind another
      proxy; a strict CSP checked in a real browser; consistent online backup,
      restore, upgrade and break-glass scripts in `deploy/`
- [x] **CI** — backend tests with coverage gate, frontend typecheck / tests /
      build, browser tests against dev servers, and a job that builds both
      images and tests the Compose stack from outside (login wall, limits,
      headers, forged `X-Forwarded-For`, backup → wipe → restore, browser test
      under the production CSP)
- [x] **Release workflow** — `v*` tag → images on GHCR with provenance and
      SBOM, plus a deployment bundle on the GitHub release
- [x] `DEPLOYMENT.md` and `MAINTENANCE.md` rewritten for the above
- [x] **Importer written** (`backend/app/importer`: export via the vendor API
      into a resumable archive, verify, dry-run, load) — **not yet run against
      the live site**

## What is left

Ordered by how much it blocks a real switch from Dozuki.

1. **Run the real export. Time-critical.** `python -m app.importer export`
   against zmb.dozuki.com with **site Administrator** credentials, so private
   and unpublished content is included. The contract contains no obligation to
   return ZMB's data, and the API dies with the subscription: an archive on
   ZMB's own disk is the only thing that makes the end date safe. The export
   needs no Reticle server and can be done today, on any machine. Then
   `verify`, then `load --dry-run`, and read the report — it is the first
   look at the private content the census could not see. `docs/IMPORT.md`.
2. **First real installation.** Tag `v1.0.0`, let the release workflow publish
   the images (first run of that workflow, and the first build on the real
   base images — see below), get a DNS name and a certificate from UZH IT,
   follow `docs/DEPLOYMENT.md`, schedule the backup, and do the restore drill
   once before anyone depends on it.
3. **Load the content, then review it with the people who wrote it.** Imported
   guides should be checked against the originals while the old site still
   exists to compare with.
4. **UZH SSO (SAML).** ZMB uses ADFS SAML on the current site and email login
   is disabled there, so staff have never typed a password for it. Until this
   exists Reticle has local accounts only, which means an admin creates each
   person and hands out an initial password. Keep local login afterwards for
   break-glass access. Needs IT: a SAML service-provider registration.
5. **Smaller gaps found while packaging:**
   - no clean-up of uploads that nothing references any more — the media
     directory only grows;
   - no administrative command line in the application: `deploy/reset-password.sh`
     reaches into the ORM directly, and the audit trail can only be read with
     SQL (there is no screen for it);
   - backups are full copies; with many videos, incremental backups (restic,
     borg) of the backup directory will be wanted;
   - dependencies are pinned to compatible ranges, not locked to hashes, so two
     builds a month apart are not byte-identical;
   - PostgreSQL has never been run — fine until concurrent editing hurts.

### Deployment: what was and was not verified

Verified by actually running it (2026-10-10): both images build; the stack
starts healthy from `compose.yaml` as non-root with a read-only root
filesystem and no capabilities; login, guide listing, image and 199 MB video
upload, `Range` requests, the 2 MB limit everywhere else, security headers,
forged `X-Forwarded-For` ignored (audit log and throttle), data surviving
`down`/`up`; backup → destroy volumes → restore, byte-identical; an upgrade
across a schema migration and the rollback from it; TLS in `internal` and
`files` mode and the behind-a-proxy mode; both browser tests through Caddy
with zero CSP violations; the bare-VM nginx configuration in `DEPLOYMENT.md`.

Not verified, because the build sandbox could reach neither Docker Hub nor
GHCR nor the public internet:

- the images were built on **stand-in base images** (Ubuntu with Python 3.12,
  the Caddy 2.11.7 binary), not on the `python:3.13-slim-bookworm`,
  `node:22-bookworm-slim`, `caddy:2.11-alpine` and `alpine:3.22` the
  Dockerfiles name. The first CI run on GitHub is the first real build;
- **Let's Encrypt** (`RETICLE_TLS_MODE=auto`) was only syntax-checked;
- the **GitHub Actions workflows** themselves have not run. Their shell steps
  were executed locally, the `uses:` steps and the GHCR push were not;
- `deploy/upgrade.sh` was exercised with `--build`, not with `docker compose
  pull` from a registry.

## Security

An adversarial review probed a running instance. Everything it found is fixed,
and each fix has a test that fails without it:

- **Image decompression bomb** (a 308 KiB PNG took the process to 882 MB) —
  a total-pixel cap is applied from the header, before anything decodes.
- **`GET /api/media/{id}` ignored visibility** (a viewer got 404 on a draft
  guide and 200 on its images) — media now follows the same visibility
  predicate as the content that shows it.
- `/docs` and `/openapi.json` were open unauthenticated — off unless
  `RETICLE_DEBUG`, and a sweep test fails if any route lacks authentication.
- No request-body or collection ceilings — 2 MB everywhere except the upload
  route, enforced on declared length and again as bytes arrive; documents are
  bounded.
- Any author could lock a colleague out of login — a browser that has signed
  in to an account before is throttled only against its own allowance.
- `trust_forwarded_for` was a trap in both positions — replaced by an explicit
  `RETICLE_TRUSTED_PROXIES` list; the old switch is refused at start-up.
- `CORS=*` would have reflected any origin with credentials — refused at
  start-up.

The deployment adds the outer layer: uvicorn runs with `--no-proxy-headers`
and Caddy overwrites `X-Forwarded-For`, so exactly one component decides what
a client's address is; the API container has no route to the outside; a strict
Content-Security-Policy; containers without root, capabilities or a writable
filesystem.

Verified genuinely solid, do not spend effort re-checking: Argon2id passwords,
session tokens stored only as HMAC digests (a stolen backup yields no live
sessions), the CSRF double-binding, role separation, draft visibility as a SQL
predicate, upload validation by decode, no SQL injection, no XSS vectors.

Still open, and inherent until SSO exists: account security is password
hygiene. Two admins minimum; review the admin list twice a year.

## Licensing

Settled, and worth not re-opening. Dozuki's published terms contain **no**
"competing product" clause — the full agreement was read; zero matches for
"compet", "benchmark" or "similar product". The only use restriction bars
reverse-engineering *their software*, not extracting *your content*, and §5
states ZMB owns its material outright. Reticle contains no third-party code,
assets, icons or branding. See `NOTICE.md`.

One open item: those are Dozuki's *standard posted* terms. UZH will have signed
an Order Form that could differ — worth one read.

---

Author: Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

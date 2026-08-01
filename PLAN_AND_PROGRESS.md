# Reticle — plan and progress

Working notes for picking this up again. Last updated 2026-08-01.

**Reticle** is a self-hosted replacement for ZMB's paid Dozuki subscription,
covering the two things ZMB actually uses: **guides** and **wikis**.

---

## How this is being built

Three steps, deliberately separated because only the first can be done without
access to the live site:

1. **Build it complete** — the platform itself, plus the migration tool.
   *This is what the repository now contains.*
2. **Verify feature parity against zmb.dozuki.com**, screen by screen.
   Capabilities only: Reticle must **not** look like a copy of the vendor's
   interface, and no vendor HTML, CSS, JavaScript or artwork exists in this
   repository or may be introduced. The checklist is in `docs/MIGRATION.md`.
3. **Bring the content across and review it** — run the importer, read the
   reconciliation report, then author and edit real guides through the UI to
   confirm the CMS can produce everything the corpus needs.

Steps 2 and 3 need the network and the site; step 1 did not have either.

## Where it stands

The application runs end to end. Both halves are now written against the same
contract — `docs/API.md` — which was not true before this session: the frontend
had been rewritten against the measured model while the backend still served the
model that census replaced.

| | |
| --- | --- |
| Backend tests | 551 passing |
| Frontend tests | 305 passing |
| Browser smoke test | `e2e/smoke.mjs` — 18/18 at 1440 / 768 / 390 px |
| Authoring round-trip | `e2e/cms.mjs` — 24/24, writes a guide and reads it back |

### Running it locally

Two processes. Backend first:

```powershell
cd C:\ProgramData\MinicondaZMB\home\t.de\reticle\backend
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then the frontend:

```powershell
cd C:\ProgramData\MinicondaZMB\home\t.de\reticle\frontend
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" run dev
```

Open <http://localhost:5173> and sign in as `thom.dehoog@zmb.uzh.ch`. The local
admin password was set when the database was seeded during the build session; it
is a throwaway development credential and is deliberately not recorded in this
repository. If it is lost, remove `backend/reticle.db` and re-seed with a new
`RETICLE_ADMIN_PASSWORD` — that discards local test content only.

Checks:

```powershell
# frontend
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" run typecheck
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" test
# backend
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m pytest
# browser, needs both servers up
$env:PLAYWRIGHT_BROWSERS_PATH="C:\ProgramData\MinicondaZMB\home\t.de\ms-playwright"
$env:RETICLE_E2E_EMAIL="thom.dehoog@zmb.uzh.ch"; $env:RETICLE_E2E_PASSWORD="<password>"
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\node.exe" e2e/smoke.mjs
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\node.exe" e2e/cms.mjs
```

Everything lives under `C:\ProgramData\MinicondaZMB\` because AppLocker blocks
executables in user-writable paths. A venv created in `%TEMP%` will not run.

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
inventoried. Before dropping anything, check against a logged-in account — and
note that the importer's `--include-private` is what reaches them.

---

## Architecture

```
reticle/
├── docs/API.md          the contract — both halves are written against it
├── docs/DEPLOYMENT.md   first install, systemd, nginx, TLS, rollback
├── docs/MAINTENANCE.md  backups, restores, people, troubleshooting
├── docs/MIGRATION.md    the importer, the mapping, and the verification checklist
├── frontend/            React 19 + TypeScript + Vite
└── backend/             FastAPI + SQLAlchemy + SQLite
    └── app/importer/    the migration tool; nothing in app imports it
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
  sanitiser to maintain, no stored-XSS vector from the editor — and no way for
  imported vendor markup to reach a reader even if it slipped through.
- **Backend serves no static files.** nginx serves the built frontend and
  proxies `/api`. Same origin in production, so CORS does not apply there.
- **Annotations are data, not pixels.** Fractions of the image, in the same
  eight colours as bullets, because a red shape on the picture and the red
  bullet beside it are one instruction. An arrow carries a *signed* vector so it
  keeps its direction; a box cannot.
- **Browsing is visual.** Sections, wiki pages and guides are reached from walls
  of pictures rather than lists of titles: a reader recognises the instrument
  they are standing in front of faster than they can read thirty lines. The
  words on a card are held to what identifies the destination. A guide's picture
  is its own first step image; a section carries one an administrator sets; and
  anything with no picture yet gets a figure drawn from its name rather than a
  blank, so a section stays recognisable before the migration has run.
- **The section is listed beside what you are reading**, scoped to that section and
  never to the institute.
- **The importer never guesses.** Anything it does not recognise stops the run
  and appears in the report. Counts come from the raw payload rather than from
  the mapped document, so a value the mapping failed to read cannot vanish from
  both sides of the comparison at once.

---

## Done

- [x] Repo, MIT licence, `NOTICE.md` recording clean-room provenance
- [x] Domain model and pure editor logic, test-first
- [x] Typed API client, auth session, role gating
- [x] Login — the whole app is behind it; any URL falls back to the login screen
- [x] Browsing: categories, guide reader, search, breadcrumbs
- [x] **Authoring GUI**: step add/delete/reorder (drag *and* buttons), Enter for
      the next bullet, Backspace to remove an empty one, Tab to indent, colour
      and flag picker, drag-drop images into per-step slots, autosave, publish
      with validation that names the offending step
- [x] People management, self-service password change
- [x] Responsive down to 360 px; hover-only controls made permanent on touch
- [x] FastAPI backend, SQLite, publish history, audit trail
- [x] CI (GitHub Actions): typecheck, both test suites, coverage gate, browser
      smoke test with screenshots kept on failure
- [x] Deployment pipeline: tagged release, symlink switch, inert until configured
- [x] `DEPLOYMENT.md`, `MAINTENANCE.md` and `MIGRATION.md`
- [x] Contract migrated to the measured model: tags, ranges, 8 colours,
      annotations, contributors, view counts, `Page`; prerequisites removed
- [x] **Backend brought up to that contract** — tags end to end with `?tags=`
      AND-filtering, wiki pages with landing-page rules and revisions, search
      across both content types, annotations, contributors, view counts,
      hidden categories, step video
- [x] **Step video** — MP4/WebM identified from their own header bytes, stored
      under a separate size cap, and gated by the same visibility rule as images
- [x] **The importer** — vendor API client with paging and retries, a mapping
      that refuses to guess, full-resolution images, annotation geometry
      normalised to fractions, idempotent re-runs, and a reconciliation report
      that fails the run rather than quietly losing content
- [x] **Visual navigation** — section, wiki and guide cards; a guide thumbnail
      taken from its first step image; a section picture an administrator sets;
      drawn placeholder artwork for anything without one yet
- [x] **A dark theme**, because a live-cell room is dark and a reader at the
      eyepiece is dark-adapted. Paper stays white.
- [x] **A section list beside every guide and wiki page**, scoped to that
      section, with the current item marked
- [x] **Every defect the adversarial tests had documented** — nine of them,
      including an arrow that made a guide permanently unsaveable and German
      tags folding to unreadable slugs. No `it.fails` remains in the suite.

## What is left

1. **Feature parity sweep against the live site** (step 2 above). Needs the
   network. Checklist in `docs/MIGRATION.md`.
2. **The migration run and content review** (step 3 above). ⚠️ **Export before
   the subscription lapses** — the API dies with it and the contract contains no
   obligation to hand the data back afterwards.
3. **Confirm the three flag colours.** The vendor encodes flag and colour in one
   field; Reticle keeps them apart. The colours the flags map to are the
   conventional renderings and are the one part of the mapping written without
   being able to see the site.
4. **UZH SSO** (#18) — ZMB uses ADFS SAML and email login is disabled, so staff
   have never typed a password here. Keep local login for break-glass access.
   Deliberately not attempted: it cannot be tested without the ADFS metadata,
   and an untested authentication path is worse than an absent one.
5. **Hidden holding categories after import.** The importer marks imported
   categories visible; which of them are really holding pens is a judgement made
   from the report, in the admin screen, not guessed from a name.

## Security

The two high-severity findings from the adversarial review are fixed and
regression-tested: the image decompression bomb (a pixel-product cap before
decode) and `GET /api/media/{id}` ignoring guide visibility. That second fix now
also covers the two new ways a file reaches a reader — a step's video slot and a
wiki page's hero image — since each was a fresh copy of the same hole.

Also closed: `/docs` and `/openapi.json` are off unless `RETICLE_DEBUG` is set,
request bodies and collections have ceilings, and `CORS=*` is refused at
start-up rather than reflecting any origin with credentials.

Verified genuinely solid, do not spend effort re-checking: Argon2id passwords,
session tokens stored only as HMAC digests (a stolen backup yields no live
sessions), the CSRF double-binding, role separation, draft visibility as a SQL
predicate, upload validation by decode, no SQL injection, no XSS vectors.

Worth one look during the parity sweep: video is **not** re-encoded, unlike
images. Shipping ffmpeg onto AppLocker-managed workstations buys little when the
bytes are served back with a fixed `Content-Type` and `nosniff` either way, but
it is a smaller guarantee than the image path gives and it should be a conscious
acceptance rather than a surprise.

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

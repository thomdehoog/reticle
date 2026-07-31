# Reticle — plan and progress

Working notes for picking this up again. Last updated 2026-07-31.

**Reticle** is a self-hosted replacement for ZMB's paid Dozuki subscription,
covering the two things ZMB actually uses: **guides** and **wikis**.

---

## Where it stands

The application runs end to end and is verified in a real browser. It is not yet
feature-complete against ZMB's live site — section "What is left" says what is
missing and why it matters.

| | |
| --- | --- |
| Backend tests | 194 passing, 95% branch coverage |
| Frontend tests | 56 passing |
| Browser smoke test | 18/18 at 1440 / 768 / 390 px |
| Production build | ~86 kB gzipped |

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
inventoried. Before dropping anything, check against a logged-in account.

---

## Architecture

```
reticle/
├── docs/API.md          the contract — both halves are written against it
├── docs/DEPLOYMENT.md   first install, systemd, nginx, TLS, rollback
├── docs/MAINTENANCE.md  backups, restores, people, troubleshooting
├── frontend/            React 19 + TypeScript + Vite
└── backend/             FastAPI + SQLAlchemy + SQLite
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
  sanitiser to maintain, no stored-XSS vector from the editor.
- **Backend serves no static files.** nginx serves the built frontend and
  proxies `/api`. Same origin in production, so CORS does not apply there.

---

## Done

- [x] Repo, MIT licence, `NOTICE.md` recording clean-room provenance
- [x] Domain model and pure editor logic, test-first
- [x] Typed API client, auth session, role gating
- [x] Login — the whole app is behind it; any URL falls back to the login screen
- [x] Browsing: categories, guide reader, search, breadcrumbs
- [x] **Authoring GUI**: step add/delete/reorder (drag *and* buttons), Enter for
      the next bullet, Backspace to remove an empty one, Tab to indent, colour
      and flag picker, drag-drop images into three per-step slots, autosave,
      publish with validation that names the offending step
- [x] People management, self-service password change
- [x] Responsive down to 360 px; hover-only controls made permanent on touch
- [x] FastAPI backend, SQLite, publish history, audit trail
- [x] CI (GitHub Actions): typecheck, both test suites, coverage gate, browser
      smoke test with screenshots kept on failure
- [x] Deployment pipeline: tagged release, symlink switch, inert until configured
- [x] `DEPLOYMENT.md` and `MAINTENANCE.md`
- [x] Contract migrated to the measured model: tags, ranges, 8 colours,
      annotations, contributors, view counts, `Page`; prerequisites removed

## In flight

- [ ] **Security fixes** — an agent was applying these when the session paused.
      Its work is **not** in this commit. See "Security" below.
- [ ] **Wiki pages** — `MarkdownBody` with tag-filtered guide-list embeds is
      written; the page viewer, page editor and backend `Page` model are not.

## What is left

Ordered by how much it blocks a real switch from Dozuki.

1. **Tags end to end** (#16) — backend `Tag` model, `?tags=` filtering, a tag
   input in the guide editor, a `/t/:tag` listing. The frontend already links to
   `/t/:tag` and the guide-list embed already queries `?tags=`. **This is the
   navigation; nothing else matters as much.**
2. **Wiki pages** (#11) — `Page` model and endpoints, viewer, editor with a
   formatting toolbar and live preview, category landing pages.
3. **Content import** (#8) — via the vendor API, `GET /guides?includePrivate=true`,
   paging at `limit=200`. Needs **site Administrator** on zmb.dozuki.com.
   ⚠️ **Export before the subscription lapses.** The contract contains no
   obligation to return your data, and the API dies with the subscription.
4. **Image annotation** (#17) — shapes over step images in the bullet's colour.
   Stored as data (fractional coordinates) so the original stays intact and it
   scales; `Annotation` is already in the model.
5. **UZH SSO** (#18) — ZMB uses ADFS SAML and email login is disabled, so staff
   have never typed a password here. Keep local login for break-glass access.
6. **Step video, PDF export, smaller gaps** (#19).
7. **Contract reconciliation loose end** (#20) — `types.ts` no longer claims a
   draft-revision workflow that does not exist; check nothing else drifted.

## Security

An adversarial review probed a running instance. **Two high-severity findings**,
both verified, both being fixed when the session paused:

1. **Image decompression bomb** — a 308 KiB PNG takes the process from 90 MB to
   882 MB RSS. Any author can OOM the VM, and a genuine 10000² stitched figure
   does it by accident. The 20 MB upload cap does not help; the fix is a
   pixel-product cap before decode.
2. **`GET /api/media/{id}` ignores guide visibility** — a viewer gets 404 on a
   draft guide and 200 on its images. The realistic path is a guide unpublished
   *because* it held something sensitive.

Also queued: `/docs` and `/openapi.json` open unauthenticated; no request-body
or collection ceilings; any author can lock a colleague out of login
indefinitely; `trust_forwarded_for` is a trap in both positions; `CORS=*` would
reflect any origin with credentials.

Verified genuinely solid, do not spend effort re-checking: Argon2id passwords,
session tokens stored only as HMAC digests (a stolen backup yields no live
sessions), the CSRF double-binding, role separation, draft visibility as a SQL
predicate, upload validation by decode, no SQL injection, no XSS vectors.

**Next session: confirm those fixes landed and the suite is green before
anything else.**

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

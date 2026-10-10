# Reticle

Step-by-step guides and a wiki for the
**Center for Microscopy and Image Analysis (ZMB), University of Zurich**.

Reticle is a self-hosted replacement for ZMB's commercial guide platform. It
covers what the facility actually uses — writing, publishing and reading
procedural guides, and the wiki pages that organise them — and it runs on
ZMB's own hardware, with ZMB's own data, without a subscription.

The name is the etched reference pattern in a microscope eyepiece: the master
everyone aligns to.

## What it does

- **Guides.** A guide has a title, a summary, a difficulty, a time estimate
  given as a range, an introduction, ordered steps and a conclusion. Each step
  carries up to three images or videos and a list of bullets; a bullet has one
  of eight colours, an optional flag — note, caution or reminder — and can be
  indented two levels.
- **Annotations.** Shapes drawn over a step image in a bullet's colour, so
  "click the red button" points at the button. They are stored as data on top
  of the untouched original, so they scale with the image and can be edited
  later.
- **Step video.** MP4 or WebM, up to 200 MB, streamed with seeking.
- **Wiki pages.** Markdown pages with a formatting toolbar and live preview. A
  page can be the landing page of a category, and can embed live,
  tag-filtered lists of guides.
- **Tags are the navigation.** A guide lives in one category and carries many
  tags, and it is the tags that put one guide under ten instrument headings.
  That is how ZMB's existing site is actually organised (see
  `PLAN_AND_PROGRESS.md`), so tags, a tag index and tag-driven guide lists are
  first-class here.
- **Search** across guides and pages: titles, summaries, tags, step text,
  page bodies.
- **Authoring in the browser.** Add, delete and reorder steps by drag or
  keyboard, drop screenshots straight onto a step, autosave while you type.
  No git, no training required.
- **Readers see what was published, not what is being typed.** Readers
  always get the last *published* version of a guide or page. An author's
  edits to something already published are held in a working copy — autosaved,
  visible to authors — until **Publish update** makes them the new version;
  **Discard changes** throws the working copy away and returns to what is
  published. Each publish increments a version and keeps an immutable
  snapshot; older versions stay readable.
- **Images sized for reading.** The original upload is kept untouched; what a
  reader's browser is sent is a display copy of bounded dimensions, so a
  40-megapixel overview does not have to be downloaded to a phone.
- **PDF export** of any guide, for the binder next to the instrument. The PDF
  of a published version is rendered once and kept, and rendering is rationed:
  when too many exports are asked for at once the server answers "busy, try
  again in a moment" (HTTP 429) rather than slowing the site down for
  everyone.
- **Mistakes can be taken back.** An administrator can delete an upload for
  good — the screenshot that should never have been taken — and a weekly
  housekeeping job removes files that nothing refers to any more.
- **Everything is behind the login.** There is no anonymous access at all.
  Three roles: viewer, author, admin.

Not included, because the measured usage of ZMB's current site says nobody
would miss them: prerequisites, comments, Q&A, translations, quizzes,
approvals.

## Try it locally in five minutes

Needs Docker with the Compose plugin; nothing else.

```bash
git clone https://github.com/thomdehoog/reticle && cd reticle

cat > .env <<EOF
RETICLE_DOMAIN=localhost
RETICLE_SECRET_KEY=$(openssl rand -base64 48)
RETICLE_VERSION=dev
RETICLE_TLS_MODE=off
RETICLE_COOKIE_SECURE=false
RETICLE_HTTP_PORT=8080
RETICLE_ADMIN_EMAIL=admin@example.org
RETICLE_ADMIN_PASSWORD=change-me-please-123
RETICLE_DEMO_PASSWORD=change-me-please-123
EOF

docker compose up -d --build
docker compose exec app reticle-entrypoint seed --demo
```

Open <http://localhost:8080> and sign in as `admin@example.org`. The demo
content gives you tagged guides with annotated screenshots, landing pages with
embedded guide lists, a wiki page and a couple of drafts;
`demo.author@example.org` and `demo.viewer@example.org` (same password) show
what the other two roles see.

When you are done, `docker compose down --volumes` removes every trace.

This configuration is for your own machine only: plain http, cookies not
marked `Secure`, passwords in a file. A real installation is
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Architecture

```
reticle/
├── docs/API.md          the HTTP contract — both halves are written against it
├── frontend/            React 19 · TypeScript · Vite · TanStack Query · TanStack Router
├── backend/             FastAPI · SQLAlchemy · SQLite · Alembic
├── compose.yaml         the deployment: two containers, one volume
└── deploy/              Caddy configuration, backup / restore / upgrade scripts
```

In production the frontend is static files served by **Caddy**, which also
terminates TLS and proxies `/api/*` to the backend. `docs/API.md` is the
contract both halves are written against. Changing it means changing both
sides; nothing else couples them.

Decisions worth knowing, because they shape the rest:

**One data path.** The frontend has a single typed HTTP client. There is no
second "offline" or "mock" implementation — two implementations of one contract
drift apart and double the maintenance. Tests inject a fake transport, so the
code under test is always the code that ships.

**Whole-document saves.** `PUT /api/guides/{id}` writes the entire guide,
including every step and bullet. That is what lets the editor autosave without a
per-field endpoint for each thing an author can change, and it makes reordering a
plain array move on the client. The write carries the `updatedAt` the editor last
saw, so a colleague's concurrent save is rejected with a conflict rather than
silently overwritten.

**Markdown renders to React elements, never to HTML.** No `innerHTML`, no
sanitiser to keep up to date, and a Content-Security-Policy with no
`unsafe-inline` in it.

**The backend serves no static files, and the proxy serves no media.** Uploads
reach a browser only through the API, where every request is checked against
the login and against what that person may read.

**SQLite, deliberately.** One institute, a handful of concurrent editors, a
database that is a file IT can back up. Schema changes are Alembic migrations,
applied when a new version starts — on an existing installation only if a
backup was taken just before, which is what `deploy/upgrade.sh` does.

## Development

Two processes: the API on port 8000 and the Vite dev server on 5173, which
proxies `/api` to it.

### Linux and macOS

Python 3.12 or newer and Node 22.

```bash
# backend
cd backend
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # → RETICLE_SECRET_KEY in .env
echo "RETICLE_COOKIE_SECURE=false" >> .env                     # plain http on localhost
python -m app.migrate
RETICLE_ADMIN_PASSWORD='<a long passphrase>' python -m app.seed --demo
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --reload
```

```bash
# frontend, in a second terminal
cd frontend
npm ci
npm run dev
```

Open <http://localhost:5173> and sign in as `admin@zmb.uzh.ch` (or whatever
`RETICLE_ADMIN_EMAIL` says) with the password you just chose.

`python -m app.migrate` is not optional: the server refuses to start on a
database whose schema it does not recognise. `backend/README.md` has the
details — configuration, migrations, seeding, the security notes.

### Windows at ZMB

The ZMB workstations add two constraints: Node and the conda tools are not on
the default `PATH`, and AppLocker blocks executables under user-writable
paths. So the project and its environments live under
`C:\ProgramData\MinicondaZMB\` — a venv created in `%TEMP%` or in your profile
will not run.

```powershell
# backend — the conda environment is described in backend/README.md
cd C:\ProgramData\MinicondaZMB\home\<you>\reticle\backend
$py = "C:\ProgramData\MinicondaZMB\envs\reticle\python.exe"
& $py -m app.migrate
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

# frontend
cd ..\frontend
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" install
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" run dev
```

Every `npm` and `python` command in this README works the same way with those
two full paths in front.

## Testing

```bash
cd backend  && python -m pytest --cov=app        # fails under 95 % branch coverage
cd frontend && npm run typecheck && npm test     # tsc, then vitest
cd frontend && npx vite build                    # the production bundle
```

Browser tests drive real Chromium through a running stack — sign in, read a
guide at three screen widths, write and publish one — and fail on console
errors or sideways scrolling:

```bash
cd frontend
npx playwright install chromium                  # once
export RETICLE_E2E_EMAIL=admin@zmb.uzh.ch RETICLE_E2E_PASSWORD='<password>'
node e2e/smoke.mjs                               # needs both dev servers and the demo content
node e2e/cms.mjs
RETICLE_E2E_BASE=http://localhost:8080 node e2e/smoke.mjs   # or against the Docker stack
```

CI (`.github/workflows/ci.yml`) runs all of the above, then builds both Docker
images, starts them with `compose.yaml`, and checks the assembled thing from
outside: the login wall, upload limits, the security headers, a backup taken
while a file is being uploaded and the restore from it, and the browser test
under the production Content-Security-Policy.

What a build takes from elsewhere is pinned: Python packages by hash
(`backend/requirements.lock`, generated from `requirements.txt` — the command
is in `docs/MAINTENANCE.md`, section 5), npm packages by `package-lock.json`,
GitHub Actions by commit SHA. Dependabot proposes the updates.

## Running it for real

- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — first install with Docker
  Compose, the HTTPS options (including a certificate issued by university IT),
  running behind another proxy, upgrading, rolling back, moving hosts.
- [`docs/MAINTENANCE.md`](docs/MAINTENANCE.md) — backups and restores, people,
  updates, logs, disk and housekeeping, monitoring, and a table of what is
  usually wrong.

Releases are cut by pushing a version tag (`v1.2.0`):
`.github/workflows/release.yml` publishes `ghcr.io/thomdehoog/reticle-app` and
`reticle-web` and attaches a small deployment bundle to the GitHub release. A
server pulls; nothing pushes to it. A server runs the release named in its
`.env` — there is no implicit `latest` — and moves to another one with
`deploy/upgrade.sh`, which backs up first.

## Migrating existing content

ZMB's existing guides and wiki pages are exported through the vendor's
official API using ZMB's own credentials, never by scraping, and loaded with
the importer in `backend/app/importer`. [`docs/IMPORT.md`](docs/IMPORT.md) is
the procedure; read `NOTICE.md` first. The one time-sensitive point: **export
before the subscription lapses**, because the API goes away with it and the
contract contains no obligation to hand the data back afterwards.

## Licence and provenance

Reticle is MIT licensed — see `LICENSE`. It is an independent implementation
containing no third-party proprietary code, assets, icons or branding; all
artwork here is original. Guide content belongs to ZMB and is not covered by the
MIT grant. The reasoning is written up in `NOTICE.md`.

## Author

Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Center for Microscopy and Image Analysis (ZMB), University of Zurich

# Reticle

Step-by-step guides and standard operating procedures for the
**Center for Microscopy and Image Analysis (ZMB), University of Zurich**.

Reticle is a self-hosted replacement for ZMB's commercial guide platform. It
covers the part the facility actually uses — writing, publishing and reading
procedural guides — and it runs on ZMB's own hardware, with ZMB's own data,
without a subscription.

The name is the etched reference pattern in a microscope eyepiece: the master
everyone aligns to.

## What it does

- **Categories → guides → steps.** A guide has a title, summary, difficulty, a
  time estimate, an introduction, ordered steps and a conclusion, and it can
  declare prerequisite guides.
- **Steps** carry up to three images and a list of annotated bullets. Bullets
  have a colour and an optional flag — note, caution, warning or reminder — and
  can be indented two levels.
- **Authoring in the browser.** Anyone with the author role writes guides
  directly in the app: add, delete and reorder steps by drag or keyboard, drop
  screenshots straight onto a step, autosave while you type, publish when ready.
  No git, no Markdown, no training required.
- **Draft and published are separate.** Editing a published guide never breaks
  the version people are reading. Each publish increments a version and stores
  an immutable snapshot.
- **Everything is behind the login.** There is no anonymous access at all.

## Architecture

```
reticle/
├── docs/API.md        the HTTP contract — the single source of truth
├── frontend/          React 19 + TypeScript + Vite
└── backend/           FastAPI + SQLAlchemy + SQLite
```

`docs/API.md` is the contract both halves are written against. Changing it means
changing both sides; nothing else couples them.

Two decisions worth knowing, because they shape the rest:

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

## Running it

Node and the conda tools on the ZMB workstations are not on the default PATH, and
AppLocker blocks executables under user-writable paths — so this project lives
under `C:\ProgramData\MinicondaZMB\home\t.de\`. See `docs/DEPLOYMENT.md` for
server installation.

### Frontend

```powershell
cd frontend
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" install
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" run dev
```

Serves on <http://localhost:5173> and proxies `/api` to the backend on port 8000.

### Backend

See `backend/README.md` for the conda environment and startup command.

## Testing

```powershell
cd frontend
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" test        # vitest
& "C:\ProgramData\MinicondaZMB\envs\lasxapi_extended\npm.cmd" run build   # typecheck + build
```

Backend tests run under pytest — see `backend/README.md`.

## Migrating existing content

ZMB's existing guides are exported through the vendor's official API using ZMB's
own admin credentials, never by scraping. Read `NOTICE.md` before running the
importer, and note the one time-sensitive point: **export before the subscription
lapses**, because the API goes away with it and the contract contains no
obligation to hand the data back afterwards.

## Licence and provenance

Reticle is MIT licensed — see `LICENSE`. It is an independent implementation
containing no third-party proprietary code, assets, icons or branding; all
artwork here is original. Guide content belongs to ZMB and is not covered by the
MIT grant. The reasoning is written up in `NOTICE.md`.

## Author

Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Center for Microscopy and Image Analysis (ZMB), University of Zurich

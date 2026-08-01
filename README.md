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

- **Tags are the navigation.** A guide sits in one category and carries many
  tags; wiki pages embed tag-filtered guide lists. That is how one instrument
  guide appears under every heading it is relevant to, and it is what the live
  corpus actually does — guides live in hidden holding categories and surface
  through tags.
- **Categories → guides → steps.** A guide has a title, summary, difficulty, a
  time *range*, an introduction, ordered steps and a conclusion.
- **Steps** carry up to four images, an optional video, and a list of annotated
  bullets. Bullets have one of eight colours and an optional flag — note,
  caution or reminder — and can be indented two levels.
- **Annotations** are shapes drawn over a step image in the colour of the bullet
  they belong to. They are stored as fractions of the image rather than burned
  into it, so the original stays intact and they scale with the picture.
- **Wiki pages**, including category landing pages, written in Markdown with
  guide lists embedded by tag.
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

`backend/app/importer/` reads the vendor's official API and writes the corpus
into Reticle — guides, steps, bullets, tags, wiki pages, every image at full
resolution, and the annotation shapes drawn on them. It refuses to guess: any
value it does not recognise stops the run and appears in the report.

```powershell
python -m app.importer.run --base-url https://zmb.dozuki.com --dry-run --report dry-run.txt
```

The public catalogue needs no credentials; a token is only required to include
private guides. `docs/MIGRATION.md` has the full field-by-field mapping, the
reconciliation report format, and the checklist for verifying the result against
the live site.

Read `NOTICE.md` before running it, and note the one time-sensitive point:
**export before the subscription lapses**, because the API goes away with it and
the contract contains no obligation to hand the data back afterwards.

## Getting the data out again

Reticle exists because ZMB's material was held somewhere it could only be
retrieved through an API that ends with the subscription. So the way out is part
of the product, not a favour performed later with a database client:

```powershell
python -m app.portability export --archive D:\reticle-export.tar.gz
python -m app.portability restore --from D:\reticle-export.tar.gz
```

The archive is documented JSON plus the actual image and video files, each with
a checksum — readable by another platform without running Reticle, and
restorable into an empty database. `docs/EXPORT.md` describes the format
completely enough to write an importer against. The test suite exports a corpus,
restores it and compares the two on every run, because an export nobody has
restored is a hypothesis.

Administrators can take the same export over HTTP at `/api/export/archive`.

## Licence and provenance

Reticle is MIT licensed — see `LICENSE`. It is an independent implementation
containing no third-party proprietary code, assets, icons or branding; all
artwork here is original. Guide content belongs to ZMB and is not covered by the
MIT grant. The reasoning is written up in `NOTICE.md`.

## Author

Thom de Hoog — <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
Center for Microscopy and Image Analysis (ZMB), University of Zurich

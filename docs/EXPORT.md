# Getting your data out

Reticle exists because ZMB's documentation was held in a platform that returned
it only through an API that ends with the subscription. Building a second system
with the same property would be repeating the mistake at ZMB's own expense, so
the way out is part of the product.

This document describes the export format completely enough to write an importer
for a different platform **without reading Reticle's source**. That is the point
of it: if the next move is to something else, nobody should have to reverse
engineer a database file.

## Taking an export

Three ways, all producing the same thing.

```powershell
# A directory: the JSON document plus a media folder. Best for a scheduled copy.
python -m app.portability export --out D:\reticle-export

# A single file, for handing to somebody.
python -m app.portability export --archive D:\reticle-export.tar.gz
```

Or over HTTP, as an administrator:

| Method | Path                   | Returns                                        |
| ------ | ---------------------- | ---------------------------------------------- |
| GET    | `/api/export`          | The JSON document. No file bytes.               |
| GET    | `/api/export/archive`  | `.tar.gz` of the document and every media file. |

Both are administrator-only and both are written to the audit log: this is the
entire institute's documentation in one request.

The command line matters as much as the endpoints — an export is what you want
when the application will not start, and it belongs in cron next to the database
backup, where it needs no session and no browser.

## Putting one back

```powershell
python -m app.portability restore --from D:\reticle-export.tar.gz
```

Restores into an **empty** database; it refuses one that already holds guides or
pages, because merging two corpora is a different operation with different
answers. It exits non-zero if any file was missing or failed its checksum, so a
script cannot mistake "finished" for "correct".

Identifiers are preserved rather than reminted — a guide's ULID appears in its
revision snapshots, in the provenance records and in whatever people have
bookmarked, so a restore that renumbered everything would be a different corpus
that merely looked the same.

Accounts come back **without credentials** (see below), so everybody signs in
again after a restore.

## What is in the archive

```
reticle-export.json
media/<mediaId>.<ext>      one file per image or video
```

## The document

Top level:

| Key               | What it holds                                              |
| ----------------- | ---------------------------------------------------------- |
| `reticleExport`   | Format version, when it was taken, and per-entity counts.   |
| `users`           | Accounts, with **no** credential of any kind.                |
| `categories`      | The section tree; `parentId` refers to another entry.        |
| `tags`            | `{id, slug, name}`.                                          |
| `media`           | One entry per file: metadata, checksum, and its path.        |
| `guides`          | Whole guides, steps and bullets included.                    |
| `pages`           | Whole wiki pages.                                            |
| `guideRevisions`  | Immutable publish snapshots, `{guideId, version, document}`.  |
| `pageRevisions`   | The same for pages.                                          |
| `provenance`      | Where a migrated document came from, if it was imported.      |

`reticleExport.formatVersion` is **1**. It is the format's own version, not the
application's: a reader that understands 1 can say so, and a later Reticle that
changes the shape has to change this number rather than quietly emitting
something different under the same name.

### Guides and pages are the API's own shapes

A guide in the export is byte-for-byte what `GET /api/guides/{id}` returns, and a
page is what `GET /api/pages/{id}` returns. There is deliberately no second
contract: `API.md` documents both, and the export cannot drift from the thing
that is already tested.

The parts most worth knowing, because they are the parts a naive importer drops:

- `steps[].bullets[]` carry `color` (one of eight), `icon` (`note`, `caution`,
  `reminder`, or null) and `level` (0–2). Colour and flag are separate axes.
- `steps[].media[].annotations[]` are the shapes drawn over a picture, as
  **fractions** of it (`x`, `y`, `width`, `height` in 0..1, with a little
  tolerance past the edge). An arrow carries a *signed* extent because its
  direction is the point; a rectangle or ellipse does not. The colour comes from
  the same palette as bullets, and that pairing is meaningful — a red shape on
  the picture and the red bullet beside it are one instruction.
- `steps[].video` is a media reference or null.
- `tags` is a list of slugs; the guide's own category is `categoryId`.
- `isQuickLink` marks a guide the facility promoted to the front page or a
  category page. A boolean is the easiest field in an export to lose without
  anyone noticing, so the round-trip test sets it deliberately.
- `visibility` is `everyone` or `staff`, and is independent of `status`: a staff
  guide is published and finished, and is shown to authors and administrators
  only. An importer that ignores this field republishes the facility's internal
  procedures to everyone, and nothing about the restored corpus looks wrong. An
  archive written before this field existed carries the same format version and
  simply has no such key; those guides restore as `everyone`, which is what they
  were.
- `timeRequiredMinMinutes` / `timeRequiredMaxMinutes` are a range, either end
  possibly null.

### Media entries

```json
{
  "id": "01J...",
  "kind": "image",
  "contentType": "image/png",
  "byteSize": 48231,
  "width": 1920,
  "height": 1080,
  "durationSeconds": null,
  "alt": "The objective turret",
  "file": "media/01J....png",
  "sha256": "…",
  "annotations": []
}
```

`file` is the path inside the archive. `sha256` is computed from the bytes on
disk at the moment of export, not recorded at upload, so it describes the file
actually being handed over — a corrupted media store shows up in the export
rather than three years later.

**The archive carries the files themselves, not links to them.** A manifest of
URLs is worthless the day the server is switched off, which is exactly the day an
export gets used.

### Accounts carry no credentials

`users` entries are `{id, email, displayName, role, isActive, createdAt}` and
nothing else. No password hash, no session token, no throttle ledger. This file
gets copied onto a laptop and emailed to whoever is doing the migration; it
should be worth nothing to whoever else ends up with it.

A destination system needs to know who wrote what, which is why the accounts are
there at all — `guides[].author`, `lastEditedBy` and `contributors[]` refer to
them by id.

## Writing an importer for another platform

Read `reticle-export.json`, check `formatVersion`, then walk `guides` and
`pages`. Everything else is referenced by id from those two.

The mapping decisions that will cost you if you get them wrong are the same ones
that were hard coming *in* to Reticle, and they are written out in
`MIGRATION.md`: the eight bullet colours are all in use and none can be folded
into another; annotations are data rather than pixels and lose their meaning if
flattened into the image; and a time estimate is a range because that is how
long a procedure honestly takes.

## Verifying an export before you trust it

```powershell
# Restore it somewhere disposable and read it.
python -m app.portability restore --from D:\reticle-export.tar.gz
```

That is the only check worth anything. The test suite does exactly this on every
run — builds a corpus, exports it, restores it into an empty database and
compares the two documents field for field — because an export nobody has
restored is a hypothesis.

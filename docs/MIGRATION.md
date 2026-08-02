# Migrating ZMB's corpus into Reticle

This document is written for whoever runs the migration — including an agent
picking the work up cold. It covers what the importer does, how to run it, the
field-by-field mapping it applies, and the checks that decide whether the result
can be trusted.

Two things were deliberately **not** done in the build session that produced
this, because they need access to the live site and the build environment had no
outbound network at all:

1. A screen-by-screen comparison of Reticle against zmb.dozuki.com, confirming
   every function is present.
2. The migration run itself, and the review of the guides it produces.

Everything below exists to make those two steps mechanical.

---

## What is imported, and what is not

| Imported | Not imported |
| --- | --- |
| Guides: title, summary, introduction, conclusion, difficulty, time range | Vendor HTML, CSS, JavaScript, icons, fonts, branding |
| Steps: order, title, bullets with colour, flag and indent level | Anything about the vendor's *appearance* |
| Every step image, at the largest rendition available | Externally hosted embeds (they cannot be self-hosted; reported instead) |
| **Image annotations** — shape, colour and position | Comments, favourites, answers, quizzes, courses, approvals |
| Step video (MP4/WebM), with its poster frame | Per-author accounts (see "Authorship" below) |
| Tags, and the categories guides sit in | |
| The featured-guide flag, which becomes a quick link | |
| Wiki pages, including category landing pages | |

**No third-party markup crosses the boundary.** Rendered HTML is reduced to text
and to Reticle's own structures in `app/importer/mapping.py`; wiki syntax is
converted to Markdown. Reticle renders Markdown to React elements and has no
`dangerouslySetInnerHTML` anywhere, so this is not a stylistic preference — it
is what keeps the stored-XSS surface at zero and keeps the provenance clean.
Reticle's look is its own; see `NOTICE.md`.

## Running it

The public catalogue needs no credentials. A token is only required to include
private guides.

```powershell
# Rehearsal: fetch and map everything, write nothing, produce the full report.
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m app.importer.run `
    --base-url https://zmb.dozuki.com `
    --dry-run --report migration-dry-run.txt --json-report migration-dry-run.json

# The real run.
C:\ProgramData\MinicondaZMB\envs\reticle\python.exe -m app.importer.run `
    --base-url https://zmb.dozuki.com `
    --author-email thom.dehoog@zmb.uzh.ch `
    --report migration.txt --json-report migration.json
```

Useful flags:

| Flag | What it is for |
| --- | --- |
| `--dry-run` | Fetch and map, write nothing. Always do this first. |
| `--limit 5` | Import a handful, look at them, then run the rest. |
| `--skip-media` | Text only. Fast rehearsal; never a finished migration. |
| `--include-private` | Include private guides. Needs `--token` with administrator rights. |
| `--allow-unmapped` | Finish despite values the importer does not recognise. |
| `--guides-only` / `--pages-only` | Split the run. |

**Exit codes**: `0` success and reconciled, `2` the run stopped, `3` unmapped
values were found, `4` the counts did not reconcile. A non-zero exit is the
tool telling you not to trust the result yet.

> ⚠️ **Export before the subscription lapses.** The API goes away with it, and
> the contract contains no obligation to hand the data back afterwards.

## The reconciliation report

This is the part that matters. The importer counts what the *payload* contained
— steps, bullets, images, annotations, videos — and separately counts what it
actually wrote, then compares them guide by guide:

```
Totals, site versus Reticle
  steps             1443 ->   1443  ok
  bullets           7891 ->   7891  ok
  images            3120 ->   3120  ok
  annotations       1904 ->   1904  ok
  videos              90 ->     90  ok
```

The counts come from the raw JSON deliberately. If they came from the mapped
structure, a bullet the importer failed to understand would vanish from both
sides at once and the run would reconcile perfectly while losing a safety
warning.

Anything the mapping did not recognise is listed under **Unmapped values**, with
a count. Each line is a decision, not a warning:

```
Unmapped values (7 occurrences)
      5  bullet: teal
      2  markup_shape: freehand
```

The fix is to extend the tables in `app/importer/mapping.py` and run again — not
to pass `--allow-unmapped` and move on.

### Where a missing feature will show up

The report has a second list, and for the parity sweep it is the more
interesting one:

```
Fields the source carries that Reticle does not read (12)
Not losses — but this is where a missing feature shows up.
      9  quiz
      3  required_tools
```

These do not fail the run: nothing was lost, because nobody asked for those
fields. They are the only *mechanical* way to discover a capability the live
site has and Reticle does not — a field nobody looks at cannot go missing from
a count, so without this list an unknown feature would be invisible.

**Read this list before starting the screen-by-screen comparison.** It tells you
where to look.

## The mapping, field by field

### Bullets

| Source | Reticle |
| --- | --- |
| `black` `red` `orange` `yellow` `green` `light_blue` `blue` `violet` | the same eight colours, `icon: null` |
| `icon_note` | colour `blue`, flag `note` |
| `icon_caution` | colour `orange`, flag `caution` |
| `icon_reminder` | colour `violet`, flag `reminder` |
| `level` 0/1/2 | the same; anything deeper is clamped and reported |

⚠️ **Confirm the three flag colours on the first real run.** The vendor encodes
flag and colour in one field; Reticle keeps them apart so a bullet can be
flagged without losing the colour that ties it to its annotation. The colours in
that table are the conventional renderings, and they are the one part of this
mapping that was written without being able to see the site.

### Annotations

Shapes are `rectangle`, `ellipse`, `arrow`. A `circle`/`oval` becomes an
ellipse; a `line` becomes an arrow, because a colour pointing at nothing is
worse than an arrowhead nobody asked for. Coordinates are normalised to
fractions of the image (0..1), accepting either fractions or percentages, and
either `x/y/width/height` or two corners.

The annotation's colour comes from the same eight-colour palette as bullets, and
that pairing is the point: **a red shape on the picture and the red bullet
beside it are one instruction.** If the verification step finds annotations
whose colours no longer line up with their bullets, that is a defect, not a
cosmetic difference.

### Time estimates

Parsed into a range: `timeRequiredMinMinutes` and `timeRequiredMaxMinutes`.
Handles `30 minutes`, `30 - 90 minutes`, `1 hour 30 minutes`,
`30 minutes to 2 hours`, `00:30 – 01:30`, integers in seconds, and
`{"min": …, "max": …}`. Anything else is reported rather than guessed.

### Media

The **largest** rendition on offer is taken (`original` before `huge` before
`large` …). A step image is often a screenshot of an acquisition dialog, and the
display-sized copy loses the only thing it was there to show.

Every image is re-decoded and re-encoded through the same validation an upload
goes through, which strips camera EXIF (serial numbers, occasionally GPS) and
makes a decompression bomb impossible.

A step may carry up to **four** images plus one video. A step exceeding that
fails loudly rather than being truncated.

### Wiki pages

`CATEGORY` wikis become the landing page of the category of the same name;
everything else becomes an ordinary wiki page. Wiki syntax converts to Markdown:
headings, bold, italic, links, bullet lists.

**Guide embeds are left as literal text** — `[guide|1234|Align the laser]`
arrives on the page exactly as written. Reticle's own embed, the `guidelist`
block, selects guides *by tag*; the vendor's selects *one guide by its numeric
id*, and nothing maps an id to a tag. Translating it would produce a `guidelist`
keyed on "1234", which renders as an empty list — the reader would see nothing
where the source showed a guide, and the reconciliation counts cannot detect
that. Left as text the marker is visible, so whoever reviews the migrated
category pages can replace each one with the embed it should have been. Search
the imported pages for `[guide|` to find them all.

If a category already has a landing page, a second one is imported as an
ordinary article and noted in the report, rather than overwriting what is there.

### Authorship and visibility

Everything imported is attributed to the account named by `--author-email`.
Inventing an account per original author would create logins nobody can use and
nobody can deactivate. The original identifier and URL are kept in
`imported_records`, so any guide here can be traced back to the exact guide
there — which is what makes the side-by-side comparison possible.

**Public guides arrive published; private ones arrive as drafts.** The site's
own visibility is the only honest default.

### Re-running

The importer is idempotent. `imported_records` maps each source object to what
it created, so a second run updates rather than duplicating, and already-fetched
images are not downloaded again. A run interrupted by a network failure can
simply be repeated.

---

## Proving the content is faithful

Counting catches a run that lost half a corpus. It does not catch one where a
step arrived with the right number of bullets and different words in them, and
it does not catch content that is here and was never there.

```powershell
python -m app.importer.run --base-url https://zmb.dozuki.com --verify --report fidelity.txt
```

That re-fetches every imported guide, maps it again, and compares it with what
Reticle stores — field by field, bullet by bullet, shape by shape. It separates
two failures, and the distinction is the point:

- **Differs from the source** — a value lost or altered on the way in.
- **Content with no source** — an extra bullet, an extra step, a summary where
  the original was blank, a tag nobody applied. Nothing in this importer writes
  prose, so anything here is either a defect or an edit somebody made after the
  import. **This is the check against invented content**, and it exits `5` if
  there is any.

The rule it enforces is worth stating plainly, because the pressure to break it
is real when a source guide is thin: **never improve, reword, summarise,
translate or complete imported content.** A guide that reads better than its
original is a guide somebody will follow believing ZMB wrote it.

## Checklist for the verification step

Run these in order and report the results.

### 1. Feature parity, screen by screen

For each screen, confirm the *function* exists in Reticle. It must **not** look
like a copy of the vendor's interface — Reticle's design is deliberately its own
— so compare capabilities, never appearance.

- [ ] Guide reader: steps numbered, bullets with all 8 colours and 3 flags, indent levels 0–2, one large image with the others as thumbnails that swap it, annotations drawn in the bullet colours, video where a step has one, difficulty, time range, tags as links, contributors, view count, version and date, print.
- [ ] Guide editor: create, add/delete/reorder steps, bullet colour and flag, indent, up to 4 images per step with alt text, annotation drawing, video, tags, time range, autosave, publish, unpublish, archive, revision history.
- [ ] Wiki: read a page, embedded guide lists filled by tag, page editor with preview, category landing pages, publish/unpublish, revisions.
- [ ] Navigation: category tree with holding categories hidden, tag pages, tag index, search across guides and wiki pages.
- [ ] Administration: people (role, deactivate), categories (create, rename, re-parent, reorder, hide, delete), own password.
- [ ] Anything on the live site that is not in that list — write it down. That is the gap.

### 2. Content fidelity

- [ ] `migration.txt` reconciles: every total `ok`, no unmapped values, no skipped guides.
- [ ] Guide count matches the site. The 2026 census found **257** publicly visible guides; the true number including private ones will be higher, and `--include-private` is what reaches them.
- [ ] Pick 10 guides spanning the extremes — the longest, one with video, one with the most annotations, one with a deep indent, one in the hidden confocal holding category — and compare each against the live page: every step, every bullet, every colour, every flag, every image, every shape.
- [ ] Confirm each annotation's colour still matches its bullet.
- [ ] Confirm images are full resolution, not display-sized copies.
- [ ] Confirm no vendor HTML, class name or inline style appears in any body, introduction or bullet.

### 3. Authoring, on the imported corpus

- [ ] Create a new guide through the UI in a category that came from the import, with images, annotations and tags, publish it, and confirm it appears in the tag listings and in the embedded guide lists on the landing pages.
- [ ] Edit an imported guide, save, publish an update, and confirm the version increments and the previous revision is still readable.

Report back: what reconciled, what did not, every unmapped value, and every
capability the live site has that Reticle does not.

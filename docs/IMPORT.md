# Importing the existing guides and wiki pages

This is the runbook for moving ZMB's own content from `zmb.dozuki.com` into
Reticle. It is written for the person who administers the Dozuki site and will
run the commands once. Read `NOTICE.md` first: the import uses the vendor's
**official API** with **ZMB's own credentials**, for content ZMB owns, and
never reads the vendor's web pages.

There are two steps, and they are separate on purpose:

| Step | Command | Needs | When |
| --- | --- | --- | --- |
| 1. **Export** | `python -m app.importer export` | network access to the Dozuki site; *no* Reticle server | **now** |
| 2. **Load** | `python -m app.importer load` | the export directory and a Reticle database | whenever Reticle is ready; repeatable |

## 1. Why export first, and soon

- **The API stops when the subscription stops.** Everything the importer can
  fetch, it fetches through `https://zmb.dozuki.com/api/2.0/`. When the
  contract ends, so does that address.
- **The contract contains no obligation to hand the content back.** The posted
  terms say the content is ZMB's; they do not promise an export after
  termination (see the "Licensing" section of `PLAN_AND_PROGRESS.md`; the signed
  Order Form may differ and is worth one read).
- **The export is safe to do early.** It only reads. It writes the vendor's raw
  answers and the original media files into a directory on your disk. Nothing
  is interpreted yet, so a mistake in how Reticle maps the content can be fixed
  later by loading the same directory again — long after the API is gone.
- **You can export more than once.** A second run only fetches what is new or
  changed. Export today for safety, and again the day before the site is
  switched off for completeness.

So: do step 1 this week, verify it, copy the directory somewhere backed up.
Step 2 can wait until the Reticle server exists.

## 2. Credentials

The export works in three modes. Which one is possible on this site is the main
open question, so be exact about what is known.

### What is known

- **Anonymous access works** (verified against the live site, October 2026).
  Without signing in, the API returns every *public* guide (about 260), their
  tags, the category pages, the wiki pages, image metadata including markers,
  and author profiles.
- **About 37 guides are not visible anonymously.** The guide listing skips
  rows; these are presumably private, unpublished or team-restricted guides.
  They need an authenticated export.
- **The documented way to authenticate** is a token: `POST /user/token` with an
  e-mail address and a *Dozuki-local* password returns an `authToken`, which is
  then sent as `Authorization: api <token>`. With an administrator's token,
  `includePrivate=true` on the guide listing returns all guides.

### What is not verified

Nothing that needs a login could be tested from outside. In particular:

- whether `zmb.dozuki.com` is **single-sign-on only**, or still allows a local
  account with a password;
- whether `POST /user/token` works on this site at all, and whether it needs an
  **app id** (`X-App-Id`);
- whether `includePrivate=true` behaves as documented;
- how long a token lives;
- whether a browser session cookie is accepted by the API.

An account that exists only through UZH single sign-on has **no Dozuki
password**, so the e-mail/password route cannot work for it.

### What to try, in this order

1. **A token you already have, or that Dozuki support issues.** Ask support
   (see the message below). Then:

   ```bash
   read -rs DOZUKI_TOKEN && export DOZUKI_TOKEN
   ```

2. **A local administrator account**, if the site allows one next to SSO
   (Dozuki's user management may let an admin create a user with a password).
   The importer signs in and obtains the token itself:

   ```bash
   export DOZUKI_EMAIL=local.admin@zmb.uzh.ch
   read -rs DOZUKI_PASSWORD && export DOZUKI_PASSWORD
   export DOZUKI_APP_ID=...        # only if support says the site needs one
   ```

3. **Your browser session, as a last resort.** Sign in to the site through SSO
   as an administrator, open the browser's developer tools → Network, click any
   request to `zmb.dozuki.com`, and copy the value of its `Cookie` request
   header:

   ```bash
   read -rs DOZUKI_SESSION_COOKIE && export DOZUKI_SESSION_COOKIE
   ```

   This is **undocumented and untested**. It is plausible because the website
   and the API are the same server, and it is still the official API with your
   own login. If the site rejects it, the export stops with a clear message.

4. **Anonymously, for the public subset — do this in any case, today.** It
   needs nothing, and it secures roughly 260 of the ~300 guides while the
   credential question is being sorted out. Run the same command again with
   credentials later; it adds the private guides to the same directory.

The importer prints a loud warning whenever it runs anonymously, because an
anonymous export looks complete and is not.

Credentials are read from these environment variables and from nowhere else.
They are never written to the export directory, the manifest or the console.
`read -rs` keeps them out of your shell history. The token is sent to
`zmb.dozuki.com` only — never to the media servers the files are downloaded
from.

### A message for Dozuki support

> We are the administrators of zmb.dozuki.com (University of Zurich, Center
> for Microscopy and Image Analysis). We would like to export our own content
> through the API before our subscription ends. Our users sign in through
> SAML single sign-on, so we have no local password for `POST /user/token`.
>
> 1. How do we obtain an API token with administrator rights for our site?
> 2. Does our site require an `X-App-Id`, and if so what is it?
> 3. Is there a rate limit or a preferred time window for roughly 15,000 API
>    requests and a few thousand media downloads?
> 4. Can you provide the originally uploaded video files? The API only offers a
>    720×480 transcode.
> 5. Alternatively, can you provide a full data export of our site?

## 3. Running the export

The commands are shown twice: for the Docker deployment (`docs/DEPLOYMENT.md`),
where the `tools` service has both the data volume and a route out, and for a
plain Python environment. Export does not need the Reticle server, so the plain
form works on any machine with Python and the backend's requirements installed
— your own laptop is fine.

```bash
# Docker (run in the directory with compose.yaml; the archive lands in ./import/zmb)
docker compose run --rm -e DOZUKI_TOKEN tools \
    python -m app.importer export --site zmb.dozuki.com --out /import/zmb

# Plain Python
cd backend
python -m app.importer export --site zmb.dozuki.com --out ../import/zmb
```

Pass `-e DOZUKI_EMAIL -e DOZUKI_PASSWORD` or `-e DOZUKI_SESSION_COOKIE` instead
of `-e DOZUKI_TOKEN` for the other modes, and nothing at all for an anonymous
export.

What it does, in order: lists all guides (200 per page, until an empty page —
a short page is not the last one on this API); fetches each guide in full and
its tags; fetches the category tree and every category; fetches the wiki pages
in the `CATEGORY`, `WIKI`, `INFO` and `ITEM` namespaces; fetches the metadata of
every image used (this is where the markers are) and downloads each original,
plus the *clean* source image of every marked-up one; downloads each video in
the best encoding offered; fetches the profile of every author.

**It is safe to interrupt.** Press Ctrl-C, lose the connection, let the token
expire — then run the same command again. Everything already on disk is
skipped. Files are written under a temporary name and renamed when complete, so
a half-downloaded file is never mistaken for a finished one.

**It is polite.** Requests are sequential with a quarter of a second between
them (`--delay`). A `429`, a `5xx` or a timeout is retried up to five times
with a growing pause, honouring `Retry-After` (`--retries`).

At the end it prints counts per kind of item and lists everything that failed,
with the reason. The exit status is `0` if nothing failed, `1` if something
did (run it again), `2` if it could not work at all (credentials refused, site
unreachable).

Useful options: `--refresh` fetches every API response again instead of reusing
the copy on disk (media files are still kept); `--namespaces CATEGORY,WIKI`
limits the wiki namespaces; `--quiet` prints only warnings and the summary.

### Verify it

```bash
docker compose run --rm tools python -m app.importer verify --archive /import/zmb
# or:  python -m app.importer verify --archive ../import/zmb
```

This uses no network. It checks that every listed guide and page is present and
readable, that every image and video they use was downloaded, and that every
media file still matches the SHA-256 recorded when it was written. Run it
after the export, and again after copying the directory anywhere.

### Time and disk space

These are estimates from the public part of the site (about 260 guides, most
steps with two or three photographs); the real numbers are printed at the end
of the run.

| | Estimate |
| --- | --- |
| API requests | 10,000–15,000 (two per guide, one per image for its metadata) |
| Media downloads | 5,000–8,000 images, about 90 videos |
| Duration | **2–4 hours** at the default pace; it can run unattended |
| Disk | **allow 30 GB**. Phone photographs are 2–5 MB each as originals; screenshots are far smaller. The videos are small (the vendor's 480p transcodes). |

Check with `du -sh import/zmb` afterwards. A second run takes minutes.

### What is in the directory

```
manifest.json            what was fetched, when, with what result; checksums
api/guides/…             the raw JSON of every guide and its tags
api/categories/…         the category tree and every category
api/wikis/<NAMESPACE>/…  every wiki page
api/media/…              image and video metadata (markers, crops, sizes)
api/users/…              author profiles
files/images/…           original images
files/videos/…           videos
```

**Keep it.** It is the only copy of the content in the vendor's own format.
**Treat it as personal data:** the author profiles contain names and e-mail
addresses, and the guides may show badges, rooms and unpublished results.

## 4. Loading into Reticle

Reticle must be installed and migrated first (`docs/DEPLOYMENT.md`). Create the
Reticle accounts of current staff **before** loading, with the same e-mail
address they have on the Dozuki site: the import attributes each guide to the
Reticle account with its author's address.

### Dry run

```bash
docker compose run --rm tools python -m app.importer load --archive /import/zmb --dry-run
# or:  python -m app.importer load --archive ../import/zmb --dry-run
```

A dry run does everything except keep it: it converts every guide, checks
every image, and then rolls the database back and writes no media file. It
prints the counts and writes `import-report-dry-run.md` into the archive
directory. Read that report (section 6) before the real run. Run the dry run
while nobody is editing, as it holds the database's write lock while it works.

To try a few guides for real first:

```bash
python -m app.importer load --archive ../import/zmb --guide 15 --guide 27
```

### The real run

```bash
docker compose run --rm tools python -m app.importer load --archive /import/zmb
# or:  python -m app.importer load --archive ../import/zmb
```

Take a backup of the Reticle data volume first (`docs/MAINTENANCE.md`). Expect
20–60 minutes for the whole site; most of it is image work. The server can keep
running. The exit status is `0` if every item loaded, `1` if some failed (they
are listed in the report; everything else is in), `2` if it could not start.

| Option | Effect |
| --- | --- |
| `--dry-run` | Report what would happen; write nothing. |
| `--publish` (default) | Guides that were public on the old site are published; private and unpublished ones become drafts. |
| `--as-drafts` | Everything is imported as a draft, for review before anything is visible to viewers. |
| `--owner-email a@b` | Make one existing Reticle account the author of everything, instead of the original authors. |
| `--force` | Also overwrite imported content that was edited in Reticle since (see section 7). |
| `--markers burned` | Do not convert image markers; use the vendor's marked-up pictures as they are. |
| `--arrow-head start\|end` | Override which end of an arrow gets the head (default: decided per arrow from the picture). |
| `--namespaces …` | Wiki namespaces to load (default `CATEGORY,WIKI,ITEM`). |
| `--guide N` | Load only this guide id; repeatable. |
| `--report path` | Where to write the report. |

## 5. What is carried over, and how

### Guides

| Dozuki | Reticle |
| --- | --- |
| Title, summary | the same |
| Introduction, conclusion | **plain text**. Reticle shows these without markup, so bold and italic are dropped and a link becomes `text (https://address)`. |
| Difficulty | `Very easy` → very easy, `Easy` → easy, `Moderate` → moderate, `Difficult` → difficult, `Very difficult` → very difficult. Anything else → moderate, and reported. |
| Time required (seconds, min–max) | minutes, min–max; `0` means "not set" |
| Category | the Reticle category of the same title (see below) |
| Tags | from the guide's tag list; Reticle's tag identity is the lower-case form, so `StellUSZ` and `stellusz` are one tag |
| Steps, in order | steps |
| Step lines | bullets. Colours `black, red, orange, yellow, green, light_blue, blue, violet` map one to one; `icon_note`, `icon_caution`, `icon_reminder` become the note, caution and reminder flags (on a black bullet). Indent levels 0–2. Text is plain, as above. Unknown bullet styles take the colour of the vendor's style record and are reported. |
| Step images | media, at most three per step. A step with more is split into "… (continued)" steps, and reported. |
| Image markers | Reticle annotations on the **clean** source image (see below) |
| Step videos | video media |
| Author | the Reticle account with the same e-mail address. If there is none, an **inactive** viewer account is created with no usable password, so the name appears on the guide but nobody can sign in with it. Content with no recorded author (most category pages) is attributed to an inactive placeholder account named "Imported content". |
| Created / modified / published dates | kept |
| Public + published | published, with a version-1 entry in the history dated as on the old site |
| Private, unpublished, archived | draft |

### Image markers

On the old site a marked-up picture is a second image with the arrows and
boxes drawn into its pixels. Reticle draws annotations *over* a clean picture,
so they stay sharp and editable. For each marked-up image the importer takes
the clean source, applies the same crop, converts the markers (rectangle,
circle → ellipse, arrow), and then **compares the result with the vendor's
marked-up picture**: only if the shapes land where the vendor's pixels show
markers is the conversion used. Otherwise — and for anything Reticle has no
shape for, such as text labels — the vendor's marked-up picture is imported as
it is, and the report says which image and why. That fallback is always
correct to look at; it just cannot be edited.

### Categories and wiki pages

- The category tree is recreated. A category is named by its **display title**
  (the category internally called `Basic Guides` is shown as "Confocal
  Microscopy", and that is its name in Reticle).
- Categories named "… - hidden" (and `Image processing - hiden`) are marked as
  **hidden holding categories**: their guides are reached through tags, as on
  the old site. The report lists which categories were marked.
- A Reticle category that already exists with the same name is reused.
- Each **category page** becomes the landing page of its category. The site's
  root page becomes an ordinary page.
- **Wiki pages** become Reticle pages, converted to Markdown: headings, bold,
  italic, lists, tables, images, code blocks.
- Links to guides, pages and categories — written as `[guide|15]`, `[[Page]]`
  or as full `zmb.dozuki.com` addresses — are rewritten to the new Reticle
  addresses.
- The guide list `[guidelist|tags=StellUSZ|type=howto]` becomes Reticle's

  ````
  ```guidelist
  tags: stellusz
  ```
  ````

  which is what makes the instrument pages work.
- Anything not recognised is kept as readable text and reported — never
  dropped silently.

### What is not carried over

| Not imported | Why |
| --- | --- |
| **Original video files** | The API only offers the vendor's 720×480 transcode. That is what is imported. If staff still have the source files, re-upload those; otherwise ask support. |
| **Comments** | Not part of Reticle. They remain in the archive (`comments` in each guide's JSON). |
| **Revision history** | The API exposes only the current revision. Imported guides start at version 1. |
| **View counts** | The API does not provide them. |
| **Guide cover images** | Reticle guides have none; the files are in the archive. |
| **Underline, superscript, subscript** | Markdown has no underline (it becomes italic); `x^^2^^` becomes `x^2`, `H,,2,,O` becomes `H2O`. |
| **Links inside bullets and introductions** | Kept as text plus address, not clickable (those fields are plain text in Reticle). |
| **Flags** ("In Progress") | Reticle has no flags. Flagged guides are imported with their public/private status and listed in the report. |
| **Page tags** | Reticle pages have no tags; reported. |
| **`INFO` pages** | On a Dozuki site these are the vendor's own FAQ texts, not ZMB's content, so they are exported but not loaded. Pass `--namespaces` to include them only if you wrote them yourselves. |
| **Embedded external videos in wiki pages** | Become plain links. |
| **Prerequisites, tools, parts, documents, quizzes, data capture** | Not used on the site as far as the public guides show; not imported. They remain in the archive. |
| **User and team pages, permissions per guide** | Not imported. Reticle's roles are viewer, author and admin. |

## 6. Reading the report

`import-report.md` (or `import-report-dry-run.md`) is written into the archive
directory. From top to bottom:

1. **Header** — which archive, when it was exported and whether anonymously,
   which database, which options.
2. **Counts** — per kind (category, user, guide, page): created, updated,
   unchanged, skipped, failed. On a first run everything should be "created".
3. **Failed** — items for which *nothing* was written, each with the reason.
   A failure never affects other items. Fix the cause and run again.
4. **Skipped** — items left alone on purpose: empty pages, and content edited
   in Reticle since the last import.
5. **Warnings**, grouped by kind, each naming the guide and step. The ones to
   act on:
   - *Steps split* — check the "(continued)" steps read well.
   - *Images imported with their markers burned in* — fine to leave; redraw
     the annotations in Reticle only where it matters.
   - *Markup that was not recognised* — look at the page and fix by hand.
   - *Media that could not be imported* — a file missing from the archive or
     in a format Reticle does not take.
   - *Imported as a draft although the original was public* — usually an empty
     step; fix and publish.
   - *Links that still point at the old site* — they will stop working.
   - *Guide lists worth checking* — lists that name several tags.
6. **Notes** — one-line facts about the run: hidden categories, tag spellings
   that merged, namespaces not loaded.
7. **Created / Updated** — every item with its new address.

After the real run, open a few guides you know well — one with arrows, one
with a video, one of the instrument pages with guide lists — and compare them
with the old site while it still exists.

## 7. Running it again

Both steps are repeatable.

- **Export again** at any time: only new and changed items are fetched.
- **Load again** at any time: the importer remembers which Dozuki item became
  which Reticle item (table `import_records`), so a second load **updates
  instead of duplicating**. An item that has not changed on the Dozuki side is
  left untouched. Addresses (`/g/…`, `/w/…`) do not change.
- **Edits made in Reticle are protected.** If a guide or page was saved,
  published or unpublished in Reticle after it was imported, a later load
  skips it and says so. `--force` overrides that and replaces it with the
  Dozuki version.
- Loading the same archive into a test instance and into production is fine;
  each database keeps its own record.

The intended sequence: export now → load into a test instance → review the
report → final export on the last day → load into production → from then on,
Reticle is the only place content is edited.

## 8. Open questions for the site administrator

From `docs/dozuki-api-notes.md`. The first two decide how the export is run;
please answer them before the final export.

1. Is the site SSO-only, or can a local administrator account with e-mail and
   password be used for `POST /user/token`? If SSO-only, how does Dozuki
   recommend obtaining an API token?
2. What is the site's `X-App-Id`, and is it required for `POST /user/token`?
3. How many guides exist in total, and how many are private, unpublished,
   archived or restricted to teams? (The anonymous listing shows about 260.)
   Compare with the count the authenticated export prints.
4. Should the current working revision of each guide be exported, or the latest
   *released* version? Are release versions or approval processes in use? (The
   importer exports the current revision.)
5. Are the "… - hidden" categories purely an organisational device, so that
   the instrument pages and tags are the real navigation? (The importer
   assumes so.)
6. In `[guidelist|tags=…]`, can several tags be given, and is matching "all" or
   "any", case-sensitive or not? (Reticle: all, case-insensitive. Every list
   with several tags is flagged in the report.)
7. Are the original video uploads retrievable anywhere, or do staff still have
   the source files?
8. Are attached documents (PDFs), embeds, quizzes, data capture, courses,
   comments or translations used anywhere and wanted?
9. Is there a rate limit or a preferred time window for the export?
10. Many guides belong to the shared "z mbstaff" account. Is per-person
    attribution wanted, and may authors' e-mail addresses from the API be stored
    in Reticle? (If not, use `--owner-email`.)

## 9. If something goes wrong

| Symptom | Meaning and remedy |
| --- | --- |
| `Signing in failed (HTTP 401/403)` | E-mail/password login is not available for this account (SSO) or needs `DOZUKI_APP_ID`. Use another mode from section 2. |
| `The site rejected the API token (HTTP 401)` | The token expired or was revoked. Get a new one and run again; the export resumes. |
| `The site refused includePrivate … public guides only` | The account is not an administrator. Private guides are missing. |
| Many `HTTP 429` retries | The site is rate limiting. Run again with `--delay 1`. |
| `video-file:… not found or not visible` | The video store did not release the file. List these for Dozuki support. |
| `verify` reports a checksum mismatch | The file was damaged in copying. Delete it and run the export again. |
| `The database has not been initialised` | Run `python -m app.migrate` first. |
| `--owner-email … is not an existing Reticle account` | Create the account, or drop the option. |
| A guide is in "Failed" | Read the reason; nothing was written for it. After a fix, load again — only that guide is affected. |

# Review request: a Word-like wiki editor, and a page's own contents in the rail

You are reviewing a **design before any code is written**. Be adversarial: the
most useful review names the decision that is wrong, the risk that is
underweighted, or the simpler design that was missed. The repository is
available to you; every claim below carries a file path you can check.

## What Reticle is

Reticle is a self-hosted replacement for a paid Dozuki subscription at ZMB
(Center for Microscopy and Image Analysis, University of Zurich). It holds
step-by-step instrument guides and long-form wiki pages. Stack: React 19 +
Vite 7 frontend, FastAPI + PostgreSQL backend. The live branch is
`claude/feature-completion-pq7h53`. Two ground rules from `docs/NEXT_SESSION.md`
bind every change: no vendor (Dozuki) markup, styling or artwork may enter the
repository, and both test suites stay green (`pytest` in `backend/`, `npm test`
+ `npm run typecheck` in `frontend/`).

## The ask (from the facility)

1. A **lightweight editor** for wiki pages: write without typing markup —
   bold, italic, different text styles and sizes, links.
2. **Easy links to guides** from inside the prose.
3. The page's **sections listed on the left**; clicking one jumps to that part
   of the page.

The named design reference is **Bear (bear.app)**: simplistic,
what-you-see-is-what-you-get, one clean writing column, and a **simple compact
option bar at the bottom** rather than a Word-style ribbon. Bear is a useful
reference beyond aesthetics because it is architecturally the same bet this
design makes: a rendered editing surface with markdown as the stored form
underneath.

## The architecture that exists, and the doctrine in it

- **A wiki page's body is markdown text** (`pages.body`, one TEXT column).
  The editor (`frontend/src/pages/PageEditorPage.tsx`) is a textarea with a
  toolbar that inserts markdown syntax, beside a live preview. Its doc comment
  records a deliberate decision: *"a rich-text editor that stores HTML would
  put arbitrary markup into the database and force a sanitiser to stand
  between every author and every reader for ever. Here the stored form is
  text, the renderer decides what may exist."*
- **The renderer** (`frontend/src/components/MarkdownBody.tsx`) renders
  markdown to React elements via react-markdown + remark-gfm — never to an
  HTML string, no `dangerouslySetInnerHTML`, raw HTML ignored by design. A
  2026-08-03 adversarial pass verified this posture (10 XSS payloads inert).
- **Two custom fences** extend markdown: ` ```guide ` (one guide, by slug,
  rendered as a live row) and ` ```guidelist ` (every guide carrying given
  tags, self-updating). ZMB's real wiki pages are built out of these.
- **The left rail** (`frontend/src/components/SideRail.tsx`) has two labelled
  areas: *Navigation* (the path down to where the reader stands) and *Content*
  (what is here). While reading a wiki page the rail already fetches that page
  (`RailGroups`, via `api.getPage`) to learn its category, and shows the
  category's groups.
- **Hash navigation exists**: `useScrollToHash` in
  `frontend/src/components/AppShell.tsx` scrolls to `#anchor` targets with a
  ~60-frame retry for content that arrives over the network. The rail's group
  links already use it (`/c/widefield#group-thunder`).
- **Autosave and conflicts are text-shaped**: `useAutosave` debounces saves;
  a refused write offers the author both versions as text
  (`SaveConflict`). Revision history stores and re-renders body text.
- **Real content is at stake**: 20 real ZMB wiki pages (and 26 guides, of 257)
  are already imported into a demo instance, and full migration is pending.
  Imported bodies were produced by an importer whose fidelity is verified
  field-by-field — content must not be silently rewritten.

## The proposed design

### D1. The stored form stays markdown; the editor becomes a WYSIWYG view over it

The server, the API contract, the database, the sanitiser-free renderer, the
text-shaped conflict/revision machinery, and the imported corpus all stay
exactly as they are. The new editor parses `body` into a document model when
the page opens, the author edits the rendered form directly (Word-like), and
the model serialises back to markdown. The server never learns anything
changed. **The entire feature is frontend-only — zero backend changes.**

### D2. "Sizes of text" means heading levels, not font sizes

The bar offers Paragraph / Heading / Subheading (H2/H3), bold, italic,
bulleted and numbered lists, link, table — not fonts, colours or point sizes.
Three reasons: markdown cannot store font sizes, so offering them would force
the stored form to change; the left-hand contents the facility asked for is
*built from* headings — a page structured by font sizes has no structure a
contents list can read; and one visual system across every page is what makes
the site readable. Asks 1 and 3 are one feature: choosing "Heading" in the
editor is what makes a section appear in the rail.

### D3. Editor library: TipTap (ProseMirror-based), with markdown serialisation

Proposed: `@tiptap/react` + StarterKit + Link + Table extensions, plus two
custom **atom nodes** for the ` ```guide `/` ```guidelist ` fences, rendered
inside the editing surface as React NodeViews — reusing the existing
`GuideEmbed`/`GuideListEmbed` components read-only, so an author sees the real
rows, not a placeholder. With the surface itself rendered, the side-by-side
preview goes away entirely.

Markdown in/out via a serialisation bridge (`tiptap-markdown`, or
`prosemirror-markdown` with a hand-written schema mapping). **This bridge is
the highest-risk component** — see R1.

Alternative worth weighing: **Milkdown**, a WYSIWYG-markdown editor built on
remark — the same parser family the viewer uses, so editor and renderer would
agree on markdown's meaning by construction. Cost: smaller ecosystem, its own
theming system to fight, churnier API. The review should weigh in (Q1).

**The surface is Bear, not Word.** One writing column with no chrome around
it — the title already sits above the body at its published size, and the
body is edited looking exactly as it reads. The controls are a single compact
**icon bar pinned at the bottom of the writing surface** (Bear's layout):

    H▾   •≡▾   B   I   🔗   ⧉guide   ⊞   ⋯

- **H▾** — Paragraph / Heading / Subheading.
- **List ▾** — bulleted / numbered.
- **B**, **I** — bold, italic (also ⌘/Ctrl-B, -I).
- **🔗** — link (URL, or picked from search).
- **⧉** — link to a guide (the picker, D4).
- **⊞** — table.
- **⋯** — the rarer inserts: one-guide embed, guide list (their existing
  dialogs), and the markdown source toggle if it survives Q2.

Every control carries an accessible name and a tooltip; the icons are drawn in
`components/icons.tsx` like every other icon in the app (original artwork —
nothing copied from Bear or the vendor). Styling by hand in `app.css` like the
rest of the visual system; TipTap is headless, so nothing has to be fought.

### D4. Guide links in prose: a picker over the existing search

A toolbar action "Link to a guide" opens a dialog that searches via the
existing `api.search()`, filtered to guides; choosing one inserts an ordinary
internal link (`[Guide title](/g/slug)`) at the cursor. In the stored form
this is a plain markdown link; the renderer already routes internal paths
through the SPA router (`MarkdownLink`). This is deliberately distinct from
the existing "Insert one guide" (a full row embed) and "Insert guide list"
(tag-gathered) — those stay for their jobs; this is for "this guide, here, in
this sentence".

### D5. The page's own sections in the rail's Content area

While reading a wiki page (`/w/:slug`), the rail's *Content* area lists the
page's headings instead of the category's groups. This fits the rail's own
doctrine — *Content* answers "what is here", and inside a long page, what is
here is its sections. The way back out (the category, the front page) is
already the *Navigation* area's job.

Mechanics:

- A new `domain/toc.ts`: heading extraction from markdown via remark (the
  parser the renderer already uses — never a regex over source text), and one
  shared slug function producing stable anchor ids (unicode kept — ZMB writes
  German — duplicates deduped `-2`, `-3`; a distinct prefix so heading anchors
  can never collide with the existing `group-…` anchors).
- `MarkdownBody` heading components gain `id` attributes from the same
  function.
- `RailGroups` already fetches the open page; the fetch carries the body, so
  the TOC costs no extra request. Entries link to `/w/slug#anchor`;
  `useScrollToHash` already performs the jump, retries included.
- Headings whose only content is guide lists are still real sections (the
  category-page variant that hides guide lists is a different screen and is
  untouched).

### D6. Scope fence (what this deliberately does not do)

- No font sizes, colours, alignment, or arbitrary styling (D2).
- No change to guide *steps* editing, and no contents rail for guide steps.
- No editor-side contents navigation (the reader's rail is the ask).
- **No image-insertion button yet — and the reason is a backend rule, not an
  oversight.** Media visibility is strictly foreign-key-based
  (`backend/app/routers/media.py`, `_DIRECT_REFERENCES`): a file is served to
  a reader only if a known column points at it from something readable (a
  published guide's steps, a page's hero, a section's picture, the front
  page), and a completeness test fails the suite if a new media column
  appears without a rule. An image referenced only from body *text* is
  attached by no column, so a reader would get **404 for it** — an image
  button that produces broken pictures for everyone but its author is worse
  than none. Bear's bar has one, so the gap is visible; adding it properly
  means a backend attachment mechanism (e.g. a `page_media` table written on
  save from the body's media references, readable when the page is
  published). Deliberately a follow-up, not part of this change (Q7).
- No H1 in bodies — the title field is the page's H1; the toolbar starts at
  Heading = H2, and the TOC treats any imported H1 as a top-level section
  rather than refusing it.

## Risks, named

- **R1 — round-trip fidelity.** A WYSIWYG editor re-serialises the whole body.
  If parse→serialise is not faithful, opening a real imported ZMB page and
  fixing a typo rewrites the whole text (list markers, emphasis delimiters,
  escaping, table alignment, the fences). Mitigations proposed: (a) a
  **corpus round-trip test** — every real imported wiki page and every
  fixture must survive parse→serialise→parse semantically unchanged, run in
  CI over the fixtures and runnable against a live corpus; (b) **open ≠
  dirty** — the editor marks dirty only on a real edit, so autosave never
  rewrites an untouched page; (c) accepted, once: the first real edit may
  normalise formatting (the *rendered* result must be identical; the source
  text may change shape).
- **R2 — the custom fences must be atomic.** If the guide/guidelist blocks are
  editable as text inside the surface, an author can corrupt them invisibly.
  As atom nodes they are selectable/deletable/movable but not editable;
  their dialogs (which already exist) are the way to make them.
- **R3 — paste.** Pasting from Word/webpages hands the editor HTML. The
  ProseMirror schema keeps only what it knows (bold, italic, headings, lists,
  links, tables) and everything else drops — which is the desired behaviour,
  and also the behaviour to *test*, because it is where "no sanitiser" is
  earned: nothing that is not in the schema can survive into the serialised
  markdown.
- **R4 — anchor stability.** Renaming a heading changes its anchor, and an
  external bookmark to it goes stale (scrolls to top). Accepted for v1: the
  rail always reflects the current page, and markdown offers no place to keep
  a stable id without inventing syntax.
- **R5 — a second editing surface.** Keeping the raw-markdown textarea as a
  toggle is an escape hatch for anything the surface cannot express, at the
  cost of two surfaces to keep honest. Recommendation: keep a read/write
  "Markdown" toggle in v1 precisely because imported content predates the
  editor; revisit removal once the corpus has lived in it. (Q2.)

## Implementation plan (TDD, in order — each step lands with its failing tests first)

1. `domain/toc.ts` — extraction + anchor function. Tests: German umlauts,
   duplicate headings, headings inside code fences (excluded), H1 handling,
   prefix non-collision with group anchors.
2. `MarkdownBody` heading ids. Tests: ids present and deduped in rendered
   output; `hideGuideLists` behaviour unchanged.
3. Rail: page-contents places on `/w/:slug`. Tests extend `SideRail.test.tsx`;
   the existing single-fetch shape is kept (no second request).
4. `WikiEditor` component (TipTap): schema, markdown bridge, toolbar, guide
   atom nodes with NodeViews, link picker dialog. Tests: every toolbar action
   produces the exact markdown; the fences round-trip byte-identically; paste
   of hostile/styled HTML yields only schema markdown; corpus fixtures
   round-trip.
5. `PageEditorPage` swaps the split textarea+preview for the surface (+
   markdown toggle per Q2); autosave wiring unchanged (serialise at save
   time, not per keystroke, if profiling says it matters — Q4).
6. `e2e/cms.mjs` extended: author a page through the surface, link a guide,
   see the section appear in the rail, click it, land on it.

New frontend dependencies (all MIT): `@tiptap/react`, `@tiptap/starter-kit`,
`@tiptap/extension-link`, `@tiptap/extension-table` (+ row/cell/header), and
the markdown bridge. No backend dependency changes. No API changes.

## Questions the review should answer

- **Q1.** TipTap + bridge vs Milkdown (remark-native) vs raw
  `prosemirror-markdown`: which markdown-round-trip failure modes have you
  seen in practice, and is the corpus round-trip gate (R1) sufficient
  protection, or does the stored form need a different guarantee?
- **Q2.** Keep the raw-markdown toggle (R5) or ship WYSIWYG-only?
- **Q3.** Rail: *replace* the category groups with the page's sections while
  a page is open, or stack both areas? Replacement is proposed (D5); the
  counterargument is losing "what else is in this section" one click early.
- **Q4.** Serialise on every keystroke (simple; the autosave snapshot is
  always current) or at save time (cheaper; the snapshot is a function)?
  ZMB pages run to thousands of words.
- **Q5.** Is there a simpler design that satisfies the ask? The one
  considered and rejected: keeping the textarea and only improving the
  toolbar + preview. Rejected because the ask is explicitly "like Word" —
  authors who will not type markup — but push back if you disagree with the
  premise.
- **Q6.** Anything here that erodes the no-sanitiser doctrine or the import
  fidelity guarantee in a way the mitigations miss?
- **Q7.** Images: is deferring the image button the right call given the
  visibility constraint (D6, last bullet), or should the `page_media`
  attachment mechanism be designed into this change so the bar ships
  complete? If deferred, the editor must still *render* markdown images that
  already exist in imported bodies.

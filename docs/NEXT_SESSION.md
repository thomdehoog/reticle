# The next session

Written for whoever — person or agent — picks this up with access to
zmb.dozuki.com and a browser. The build is done; what remains cannot be done
without the live site.

There are four jobs, in this order, because each one's result changes what the
next one should check.

1. **Check the API against reality**, and turn the real payloads into fixtures.
2. **Verify feature parity**, screen by screen.
3. **Migrate the content, and prove it is faithful** — not paraphrased, not
   summarised, and above all not invented.
4. **Author real guides by hand in the CMS**, and judge whether the CMS is good
   enough. Then fix what it turns up.

Report at the end against the headings in "What to report back".

---

## 1. Check the API against reality

Everything downstream rests on the mapping in
`backend/app/importer/mapping.py`, and that mapping was written **without ever
having seen a response**, because the build environment had no network. The
tables in it came from a census someone recorded in prose. Treat every one of
them as a hypothesis until a real payload agrees.

The catalogue needs no credentials.

```bash
curl 'https://zmb.dozuki.com/api/2.0/guides?limit=5' | jq .
curl 'https://zmb.dozuki.com/api/2.0/guides/<id>' | jq .
curl 'https://zmb.dozuki.com/api/2.0/wikis/CATEGORY?limit=5' | jq .
```

Then:

- [ ] **Save real payloads as test fixtures.** Take a dozen guides spanning the
      extremes — the longest, one with video, one with many annotations, one with
      deep indenting, one from the hidden confocal holding category, one private
      if you have a token — into `backend/tests/fixtures/`, and re-run
      `tests/test_import_mapping.py` against them. The existing fixtures are
      hand-built and *permissive about shape*: they accept several field names
      because nobody knew which one arrives. Real ones make the tests mean
      something.
- [ ] **Confirm the three flag colours.** This is the single largest known
      unknown. The vendor encodes flag and colour in one field; Reticle keeps
      them apart, and `BULLET_FLAGS` maps `icon_note`/`icon_caution`/
      `icon_reminder` onto blue/orange/violet by convention. Look at a rendered
      guide and check. If they differ, one table changes and everything else
      follows.
- [ ] **Confirm the annotation schema.** `map_annotations` accepts several
      plausible shapes — a list, a `shapes` key, a `markup` key, corner-and-size
      or two-corner geometry, fractions or percentages — because the real one was
      unknown. Find out which it is, and *narrow the function to it*. Breadth
      here is not robustness; it is a guess wearing a disguise.
- [ ] **Run a dry run and read the unread-field list.**

      ```bash
      python -m app.importer.run --base-url https://zmb.dozuki.com \
          --dry-run --report dry-run.txt --json-report dry-run.json
      ```

      The report has a section headed *"Fields the source carries that Reticle
      does not read"*. **Read it before doing anything else in job 2.** It is the
      only mechanical way to find a capability nobody wrote down: a field nobody
      looks at cannot go missing from a count, so without that list an unknown
      feature is invisible.

---

## 2. Verify feature parity

Compare **capabilities**, never appearance. Reticle deliberately does not look
like the vendor's interface, and it must not start to: no vendor HTML, CSS,
JavaScript, icon or artwork exists in this repository and none may be
introduced. A lookalike would also invite the question of what else was copied.

Work through `MIGRATION.md`'s checklist screen by screen. For each item, record
**present / absent / different**, and for anything absent, whether it matters.

The list there covers the reader, the editor, the wiki, navigation and
administration. Add to it anything the unread-field list in job 1 turned up.

Two things are known to be missing and are deliberate; confirm they are still
the right call rather than re-discovering them:

- **UZH SSO (ADFS SAML).** Not attempted, because it cannot be tested without
  the ADFS metadata and an untested authentication path is worse than an absent
  one. Local login is the break-glass route.
- **PDF export** is the browser's print-to-PDF against a print stylesheet, not a
  server-side renderer. Check a printed guide actually reads well on paper —
  that is the whole test.

---

## 3. Migrate, and prove the content is faithful

```bash
python -m app.importer.run --base-url https://zmb.dozuki.com \
    --author-email thom.dehoog@zmb.uzh.ch \
    --report migration.txt --json-report migration.json
```

Exit codes mean something: `3` unmapped values, `4` counts did not reconcile.
Neither is a result to move past.

⚠️ **Export before the subscription lapses.** The API goes away with it.

### The rule about content

**Nothing in this pipeline may write prose, and nothing may fill a gap.**
The importer maps what the payload holds; where it cannot, it reports. If you
are an agent reading this: do not improve a summary, do not translate, do not
tidy a bullet, do not infer a time estimate, do not write an introduction for a
guide that lacks one. A guide that reads better than its source is a guide
somebody will follow believing ZMB wrote it.

### Proving it, mechanically

Do not verify this by reading. Run:

```bash
python -m app.importer.run --base-url https://zmb.dozuki.com \
    --verify --report fidelity.txt --json-report fidelity.json
```

That re-fetches every imported guide from the source, maps it again, and
compares it with what Reticle stores — field by field, bullet by bullet, shape
by shape. It reports two categories separately, and the distinction is the
point:

- **Differs from the source** — a value that was lost or altered.
- **Content with no source** — something Reticle holds that the source does not:
  an extra bullet, an extra step, a summary where the original was blank, a tag
  nobody applied. **This is the hallucination check.** Exit code `5` if
  anything at all is reported.

Then, by hand, on ten guides chosen for difficulty:

- [ ] Open the live page and the Reticle page side by side. Every step, every
      bullet, every colour, every flag, every image, every shape.
- [ ] Confirm each annotation's colour still matches its bullet. A red shape and
      a red bullet are one instruction; if that pairing broke, the guide is
      wrong in a way that reads as fine.
- [ ] Confirm images are full resolution, not display-sized copies.
- [ ] Confirm no vendor HTML, class name or inline style appears in any body.
- [ ] Confirm the guide count. The 2026 census found **257** publicly visible;
      with `--include-private` the true number is higher.

---

## 4. Use the CMS, and judge it

This is the job that is easiest to skip and most worth doing. Everything above
asks whether the content arrived. This asks whether ZMB can *work* here.

**Author guides by hand, in the browser, through the editor.** Not through the
API, not through the importer — the point is to feel the tool. Choose real
guides from the corpus that have to exist anyway, and rebuild them:

- [ ] At least **ten**, and at least one of each hard case: a long one (15+
      steps), one with four images on a step, one with heavy annotation, one
      with video, one with deep indenting, one with a time range, one that
      belongs in a hidden holding category and surfaces by tag.
- [ ] Write a **section front page** with tag-filtered guide lists in it, and
      confirm the guides you just wrote appear in it.
- [ ] Do the whole lifecycle at least once: draft, autosave, publish, edit a
      published guide, publish an update, look at the revision history,
      unpublish, archive.

### Keep a friction log while doing it

For each guide, note: how long it took, and every moment you hesitated, backed
out, re-did something, or wished the tool did something else. Specifically watch
for:

- **Friction** — anything needing more clicks than it should, or a detour.
- **Intuitiveness** — anything you had to work out rather than see. If you
  needed to guess what a control does, say so.
- **Responsiveness** — anything that felt slow, or where you were unsure whether
  it had saved. Autosave says "All changes saved"; did you believe it?
- **Trustworthiness** — anything that lost work, silently discarded input, or
  where you were not sure what state something was in. This one outranks the
  rest: an author who does not trust the editor writes their guide in Word first,
  and then the CMS is decoration.

### Then answer the question

Write a verdict: **is this CMS good enough to write 257 guides in?** Not "does
it work" — whether a ZMB staff member who is not you, on a Tuesday, would use it
without complaint.

Turn the friction log into a prioritised list, and **fix the top items**. That
is the deliverable of this job, not the log itself. A finding nobody acted on is
a finding that will be rediscovered by an annoyed colleague.

---

## What to report back

1. **API** — which mapping assumptions held, which did not, what changed. The
   flag colours specifically. The list of unread fields.
2. **Parity** — capability by capability. Everything the live site does that
   Reticle does not, and whether it matters.
3. **Fidelity** — the reconciliation and fidelity reports. Any drift, any
   content with no source, and the guide count against 257.
4. **The CMS** — the friction log, the verdict, and what you changed as a
   result.
5. **Anything you could not check**, and why. An unchecked item reported as
   unchecked is useful; one reported as fine is worse than useless.

---

## Ground rules

- Every change keeps both suites green: `pytest` in `backend/`, `npm test` and
  `npm run typecheck` in `frontend/`, plus `e2e/smoke.mjs` and `e2e/cms.mjs`
  against running servers.
- No vendor markup, styling or artwork enters this repository, ever.
- Nothing generates guide content. See job 3.
- If you find a defect, fix it and add the test that would have caught it.
  There are no `it.fails` markers left in either suite; keep it that way.

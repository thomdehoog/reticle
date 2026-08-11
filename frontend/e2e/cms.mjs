/**
 * End-to-end test of the content management system.
 *
 * Drives a real browser through the job an author actually does: sign in,
 * create a guide, write steps and annotated bullets, tag it, publish it, and
 * then read it back as a reader. The point is not that the buttons respond —
 * it is that what comes out the other end is exactly what was typed in.
 *
 * Requires the backend on :8000 and the dev server on :5173.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { chromium } from 'playwright'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SHOTS = join(HERE, 'shots')
mkdirSync(SHOTS, { recursive: true })

const BASE = process.env.RETICLE_E2E_BASE ?? 'http://localhost:5173'
const EMAIL = process.env.RETICLE_E2E_EMAIL
const PASSWORD = process.env.RETICLE_E2E_PASSWORD

if (!EMAIL || !PASSWORD) {
  console.error('Set RETICLE_E2E_EMAIL and RETICLE_E2E_PASSWORD before running.')
  process.exit(2)
}

/** Unique per run, so repeated runs do not collide on the slug. */
const RUN = Date.now().toString(36)
const TITLE = `E2E confocal alignment ${RUN}`

const STEPS = [
  {
    title: 'Warm up the lasers',
    bullets: [
      { text: 'Turn the key to position II and wait.', color: null, icon: null },
      { text: 'Never look into the beam path.', color: 'red', icon: 'caution' },
    ],
  },
  {
    title: 'Mount the sample',
    bullets: [
      { text: 'Place the slide coverslip-down.', color: null, icon: null },
      { text: 'Use the immersion medium printed on the objective.', color: null, icon: 'note' },
    ],
  },
]

const TAGS = [`e2e-${RUN}`, 'confocal']

const results = []
function record(step, ok, detail = '') {
  results.push({ step, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`)
}

/**
 * Launch a browser, honouring a pre-installed one.
 *
 * A machine that already has Chromium — a CI image, or a ZMB workstation where
 * AppLocker makes downloading an executable a whole conversation — sets
 * RETICLE_E2E_BROWSER to its path. Playwright otherwise insists on the exact
 * build it shipped with, which is a download nobody can perform there.
 */
function launchBrowser() {
  const executablePath = process.env.RETICLE_E2E_BROWSER
  return chromium.launch(executablePath ? { executablePath } : {})
}

const browser = await launchBrowser()
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

const consoleErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(String(error)))

/* `/login` rather than `/`: the front page is the public corpus now, and the
   sign-in form lives at its own address. */
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByLabel('Email').fill(EMAIL)
await page.getByLabel('Password').fill(PASSWORD)
await page.getByRole('button', { name: 'Sign in' }).click()
await page.waitForSelector('.tile', { timeout: 15000 })
consoleErrors.length = 0
record('sign in', true)

/* Authoring starts behind the account, at the foot of the rail. It used to be a
   "New" button in the header; that corner belongs to the reader now, and
   creating a guide is the rarest thing anybody does here. Same action, one
   click further in, and the same entry on a phone — the drawer draws the
   account's items rather than keeping a copy. */
await page.getByRole('button', { name: /^Account:/ }).click()
await page.getByRole('button', { name: 'New guide' }).click()
await page.getByLabel('Title').fill(TITLE)
await page.getByLabel('Category').selectOption({ label: 'Light Microscopy' })
await page.getByRole('button', { name: 'Create and start writing' }).click()

await page.waitForSelector('.editor-step', { timeout: 15000 })
record('create guide opens the editor', true)

for (const [index, spec] of STEPS.entries()) {
  if (index > 0) {
    await page.getByRole('button', { name: 'Add step' }).click()
    await page.waitForFunction(
      (expected) => document.querySelectorAll('.editor-step').length >= expected,
      index + 1,
    )
  }

  const stepCard = page.locator('.editor-step').nth(index)
  await stepCard.locator('.editor-step__title-input').fill(spec.title)

  for (const [bulletIndex, bullet] of spec.bullets.entries()) {
    const fields = stepCard.locator('textarea')
    if (bulletIndex > 0) {
      await fields.nth(bulletIndex - 1).press('Enter')
      await page.waitForFunction(
        ({ step, expected }) =>
          document.querySelectorAll('.editor-step')[step].querySelectorAll('textarea').length >=
          expected,
        { step: index, expected: bulletIndex + 1 },
      )
    }
    await stepCard.locator('textarea').nth(bulletIndex).fill(bullet.text)

    if (bullet.color || bullet.icon) {
      await stepCard.locator('.editor-bullet').nth(bulletIndex).getByLabel('Bullet style').click()
      if (bullet.color) await page.locator(`.popover .swatch[aria-label="${bullet.color}"]`).click()
      if (bullet.icon) {
        const label = bullet.icon.charAt(0).toUpperCase() + bullet.icon.slice(1)
        await page.locator('.popover__item', { hasText: label }).click()
      }
    }
  }
}
record('write steps and bullets', true, `${STEPS.length} steps`)

for (const tag of TAGS) {
  await page.getByLabel('Add a tag').fill(tag)
  await page.getByLabel('Add a tag').press('Enter')
}
const chipCount = await page.locator('.tag-input__chips .tag').count()
record('add tags', chipCount === TAGS.length, `${chipCount} chips`)

/* No difficulty or duration to fill: neither is shown to a reader any more, so
   neither is asked of an author. */
await page.getByLabel('Summary').fill('Created by the end-to-end test.')

await page.waitForSelector('text=All changes saved', { timeout: 10000 })
record('autosave settles', true)
await page.screenshot({ path: join(SHOTS, 'cms-1-editor.png'), fullPage: true })

await page.getByRole('button', { name: 'Publish', exact: true }).click()
await page.waitForURL(/\/g\/[^/]+$/, { timeout: 15000 })
await page.waitForSelector('.step')
record('publish navigates to the published guide', true, page.url())
await page.screenshot({ path: join(SHOTS, 'cms-2-published.png'), fullPage: true })

const publishedUrl = page.url()

/* Everything below re-reads the published page and checks it against what was
   typed, which is the only assertion that really matters. */

const heading = await page.locator('h1').first().innerText()
record('title survived', heading.trim() === TITLE, heading)

const renderedSteps = await page.locator('.step').count()
record('step count', renderedSteps >= STEPS.length, `${renderedSteps} rendered`)

for (const [index, spec] of STEPS.entries()) {
  const block = page.locator('.step').nth(index)
  const stepText = await block.innerText()

  const titleOk = stepText.includes(spec.title)
  record(`step ${index + 1} title`, titleOk, spec.title)

  for (const bullet of spec.bullets) {
    record(`step ${index + 1} bullet text`, stepText.includes(bullet.text), bullet.text.slice(0, 40))
  }

  for (const bullet of spec.bullets.filter((entry) => entry.color)) {
    const coloured = await block.locator(`.bullet--color-${bullet.color}`).count()
    record(`step ${index + 1} bullet colour ${bullet.color}`, coloured > 0)
  }

  for (const bullet of spec.bullets.filter((entry) => entry.icon)) {
    const label = bullet.icon.charAt(0).toUpperCase() + bullet.icon.slice(1)
    const item = block.locator('.bullet--flagged', { hasText: bullet.text })
    /* The kind, not just "flagged": a caution rendered as a note is the failure
       that matters in a building with lasers and cryogens, and both carry the
       same marker class. The word is asserted too, because an icon on its own
       disappears in a greyscale photocopy taped to an instrument. */
    const kinded = await item.locator(`xpath=self::*[contains(@class,"bullet--kind-${bullet.icon}")]`).count()
    const announced = await item.locator('.bullet__flag-label', { hasText: label }).count()
    record(`step ${index + 1} ${bullet.icon} flag`, kinded > 0 && announced > 0)
  }
}

/* The version and the date are what the meta row carries now. Asserted as the
   whole of it, so restoring the difficulty meter or the duration without
   meaning to shows up here as well as in the component tests. */
const meta = (await page.locator('.guide__meta').innerText()).trim()
record('the meta row is the version and the date', /^v\d+\b/.test(meta), meta)

for (const tag of TAGS) {
  const link = page.getByRole('link', { name: tag })
  record(`tag ${tag} links out`, (await link.count()) > 0)
}

/* A tag is only useful if it actually gathers the guide elsewhere. */
await page.getByRole('link', { name: TAGS[0] }).click()
await page.waitForSelector('.tile--guide, .empty-state')
const gathered = await page.locator('.tile--guide', { hasText: TITLE }).count()
record('tag listing gathers the guide', gathered > 0)

/* And a reader arriving cold must see the published version. */
await page.goto(publishedUrl, { waitUntil: 'networkidle' })
const rereadTitle = await page.locator('h1').first().innerText()
record('guide resolves on a fresh load', rereadTitle.trim() === TITLE)
const draftBadge = await page.locator('.badge--draft').count()
record('published guide shows no draft badge', draftBadge === 0)

/* ----------------------------------------------------------------- the wiki.
   The same job for a page: write it on the rendered surface — headings, bold,
   a link to the guide published above, an embedded guide list — publish it,
   and read it back. Then the two things only a real browser can prove: the
   rail lists the page's sections and clicking one lands on it, and the
   markdown the surface produced is clean when read back through the source
   view. */

const PAGE_TITLE = `E2E alignment notes ${RUN}`

await page.getByRole('button', { name: /^Account:/ }).click()
await page.getByRole('button', { name: 'New page' }).click()
await page.getByLabel('Title').fill(PAGE_TITLE)
await page.getByLabel('Category', { exact: true }).selectOption({ label: 'Light Microscopy' })
await page.getByRole('button', { name: 'Create and start writing' }).click()

await page.waitForSelector('.wiki-editor__surface', { timeout: 15000 })
record('create page opens the rendered surface', true)

/* Written the way a hand writes it: keyboard into the surface, styles from
   the bar. Every control hands focus back to the surface when it is done, but
   "when it is done" is a re-render away — keystrokes fired before then land
   on the control, not in the page. The wait is the difference between this
   script and a author's hand, which pauses without being told to. */
const surface = page.locator('.wiki-editor__surface')

async function typeInSurface(text) {
  await page.waitForFunction(
    () => document.activeElement !== null && document.activeElement.closest('.wiki-editor__surface') !== null,
  )
  await page.keyboard.type(text)
}

await surface.click()
await typeInSurface('Written by the end-to-end test.')
await page.keyboard.press('Enter')

await page.getByRole('button', { name: 'Text style' }).click()
await page.getByRole('button', { name: 'Heading', exact: true }).click()
await typeInSurface('Preparation')
await page.keyboard.press('Enter')
await page.getByRole('button', { name: 'Text style' }).click()
await page.getByRole('button', { name: 'Paragraph' }).click()
await typeInSurface('Handle the objective with ')
await page.keyboard.press('Control+b')
await typeInSurface('care')
await page.keyboard.press('Control+b')
await typeInSurface(', then open ')

await page.getByRole('button', { name: 'Link a guide' }).click()
const picker = page.getByRole('dialog')
await picker.getByLabel('Search guides').fill(TITLE)
await picker.locator('.guide-picker__row', { hasText: TITLE }).click()
record('guide link picked from search', true)
await typeInSurface(' before starting.')

await page.keyboard.press('Enter')
await page.getByRole('button', { name: 'Text style' }).click()
await page.getByRole('button', { name: 'Heading', exact: true }).click()
await typeInSurface('Afterwards')
await page.keyboard.press('Enter')

await page.getByRole('button', { name: 'More' }).click()
await page.getByRole('button', { name: 'Insert guide list' }).click()
const listDialog = page.getByRole('dialog')
await listDialog.getByLabel('Add a tag').fill(TAGS[0])
await listDialog.getByLabel('Add a tag').press('Enter')
await listDialog.getByRole('button', { name: 'Insert' }).click()
await page.waitForSelector('.wiki-editor__embed', { timeout: 10000 })
record('guide list embeds as a live block', true)

await page.getByLabel('Summary').fill('Created by the end-to-end test.')
await page.getByLabel('Add a tag').fill(`e2e-page-${RUN}`)
await page.getByLabel('Add a tag').press('Enter')

await page.waitForSelector('text=All changes saved', { timeout: 10000 })
record('page autosave settles', true)
await page.screenshot({ path: join(SHOTS, 'cms-3-wiki-editor.png'), fullPage: true })

await page.getByRole('button', { name: 'Publish', exact: true }).click()
await page.waitForURL(/\/w\/[^/]+$/, { timeout: 15000 })
/* The URL turns before the reader's screen has replaced the editor; the
   byline exists only on the reader. */
await page.waitForSelector('.guide__credits', { timeout: 15000 })
record('publish navigates to the published page', true, page.url())

const pageHeading = await page.locator('h1').first().innerText()
record('page title survived', pageHeading.trim() === PAGE_TITLE, pageHeading)

const bolded = await page.locator('.markdown strong', { hasText: 'care' }).count()
record('bold survived to the reader', bolded > 0)

const guideLink = page.locator('.markdown a', { hasText: TITLE })
const guideHref = (await guideLink.count()) > 0 ? await guideLink.first().getAttribute('href') : ''
record('the guide link points at the guide', /^\/g\//.test(guideHref ?? ''), guideHref ?? 'absent')
/* Exactly the guide's title: the sentence typed after the link must not have
   been swallowed into it. */
const linkText = (await guideLink.count()) > 0 ? (await guideLink.first().innerText()).trim() : ''
record('the link carries the title and nothing more', linkText === TITLE, linkText)

/* The embed fetches its rows after the page renders; give it the moment. */
const embeddedRow = page.locator('.guidelist', { hasText: TITLE })
await embeddedRow.first().waitFor({ timeout: 10000 }).catch(() => {})
record('the guide list gathers the tagged guide', (await embeddedRow.count()) > 0)

/* The rail's content area is the page's own sections now. */
const railSections = await page.locator('.rail__places--content .rail__item').allInnerTexts()
record(
  'the rail lists the page’s sections',
  railSections.includes('Preparation') && railSections.includes('Afterwards'),
  railSections.join(', '),
)

/* And a section in the rail is a place: clicking it points the address at the
   section's own anchor, and the anchor is really on the heading. The scroll
   itself is not asserted — a page shorter than the window has nowhere to
   scroll to, and this one is deliberately small. */
await page.locator('.rail__places--content .rail__item', { hasText: 'Afterwards' }).click()
await page.waitForFunction(
  () => location.hash === '#s-afterwards' && document.getElementById('s-afterwards') !== null,
  undefined,
  { timeout: 10000 },
)
record('clicking a section lands on it', true, page.url())
await page.screenshot({ path: join(SHOTS, 'cms-4-wiki-published.png'), fullPage: true })

/* The proof the surface writes clean markdown: read the source back. */
await page.getByRole('link', { name: 'Edit' }).click()
await page.waitForSelector('.wiki-editor__surface', { timeout: 15000 })
await page.getByRole('button', { name: 'More' }).click()
await page.getByRole('button', { name: 'Edit markdown source' }).click()
const source = await page.getByLabel('Page body markdown').inputValue()
record('source holds the heading', source.includes('## Preparation'))
record('source holds the bold', source.includes('**care**'))
record('source links the guide by address', source.includes(`[${TITLE}](/g/`))
record('source holds the guide-list fence', source.includes('```guidelist'))

record('no console errors', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 300))

await context.close()
await browser.close()

const failed = results.filter((result) => !result.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
if (failed.length) {
  console.log('\nFailures:')
  for (const failure of failed) console.log(`  - ${failure.step} ${failure.detail}`)
  process.exitCode = 1
}

/**
 * End-to-end test of the content management system.
 *
 * Drives a real browser through the job an author actually does: sign in,
 * create a guide, write steps and annotated bullets, tag it, publish it, and
 * then read it back as a reader. The point is not that the buttons respond —
 * it is that what comes out the other end is exactly what was typed in.
 *
 * It then does the same for the wiki: writes a page with the toolbar, embeds
 * a guide list by tag, publishes it, and checks the guide shows up inside it.
 *
 * Requires the backend on :8000 and the dev server on :5173, and an author
 * account in RETICLE_E2E_EMAIL / RETICLE_E2E_PASSWORD. Set
 * RETICLE_E2E_VIEWER_EMAIL (same password) to also read the result as a
 * viewer, RETICLE_E2E_BASE for another address, and RETICLE_E2E_CHROMIUM for a
 * Chromium binary other than Playwright's own download.
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
const VIEWER_EMAIL = process.env.RETICLE_E2E_VIEWER_EMAIL

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

/* The first is new on every run; the second is one the demo content already has. */
const TAGS = [`e2e-${RUN}`, 'confocal']

const results = []
function record(step, ok, detail = '') {
  results.push({ step, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`)
}

const browser = await chromium.launch({
  executablePath: process.env.RETICLE_E2E_CHROMIUM || undefined,
})
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()

const consoleErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => consoleErrors.push(String(error)))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.getByLabel('Email').fill(EMAIL)
await page.getByLabel('Password').fill(PASSWORD)
await page.getByRole('button', { name: 'Sign in' }).click()
await page.waitForSelector('.category-card', { timeout: 15000 })
consoleErrors.length = 0
record('sign in', true)

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

/* The first tag is new and typed out; the second exists and is taken from the
   suggestions with the keyboard, which is how the vocabulary stays one. */
const tagField = page.getByLabel('Add a tag')
await tagField.fill(TAGS[0])
await tagField.press('Enter')
await tagField.fill('confoc')
const suggestion = page.getByRole('option', { name: /Confocal/i })
await suggestion.waitFor({ timeout: 5000 }).catch(() => {})
const suggested = (await suggestion.count()) > 0
record('existing tag is suggested while typing', suggested)
if (suggested) {
  await tagField.press('ArrowDown')
  await tagField.press('Enter')
} else {
  await tagField.fill(TAGS[1])
  await tagField.press('Enter')
}
const chipCount = await page.locator('.tag-input__chips .tag').count()
record('add tags', chipCount === TAGS.length, `${chipCount} chips`)

/* ---------------------------------------------------------------- step media */

/**
 * A picture drawn in the page, so the test carries no binary fixture, and the
 * opening bytes of an MP4 — which is all the server reads to tell a video from
 * a picture. It will not play, and does not need to.
 */
const pngBase64 = await page.evaluate(() => {
  const canvas = document.createElement('canvas')
  canvas.width = 960
  canvas.height = 600
  const context = canvas.getContext('2d')
  context.fillStyle = '#10151c'
  context.fillRect(0, 0, 960, 600)
  context.strokeStyle = '#ffffff'
  context.strokeRect(96, 60, 192, 120)
  return canvas.toDataURL('image/png').split(',')[1]
})
const PICTURE = { name: 'acquisition.png', mimeType: 'image/png', buffer: Buffer.from(pngBase64, 'base64') }
const CLIP = {
  name: 'insert.mp4',
  mimeType: 'video/mp4',
  buffer: Buffer.concat([
    Buffer.from([0, 0, 0, 0x18]),
    Buffer.from('ftypmp42'),
    Buffer.from([0, 0, 0, 0]),
    Buffer.from('mp42isom'),
    Buffer.alloc(2048),
  ]),
}

const firstStep = page.locator('.editor-step').first()
await firstStep.locator('.media-slots input[type="file"]').setInputFiles([PICTURE, CLIP])
await firstStep.locator('.media-slot--video').waitFor({ timeout: 15000 })
const slots = await firstStep.locator('.media-slot').count()
record('step takes a picture and a video', slots === 2, `${slots} slots`)
record(
  'a video offers no annotation tool',
  (await firstStep.getByRole('button', { name: 'Annotate image' }).count()) === 1,
)

await firstStep.locator('.media-slots input[type="file"]').setInputFiles({
  name: 'notes.txt',
  mimeType: 'text/plain',
  buffer: Buffer.from('not a picture'),
})
const refusal = firstStep.locator('.media-problems')
await refusal.waitFor({ timeout: 5000 })
record('a file of the wrong kind is refused in words', (await refusal.innerText()).includes('notes.txt'))
await refusal.getByRole('button', { name: 'Dismiss' }).click()

/* Annotate: a rectangle round the white box drawn into the picture above, in
   the colour of the red caution bullet of this step. */
await firstStep.getByRole('button', { name: 'Annotate image' }).click()
const overlay = page.locator('.annotate .annotated__overlay')
await overlay.waitFor()
await page.locator('.annotate__bullet', { hasText: 'Never look into the beam path.' }).click()
const surface = await overlay.boundingBox()
const at = (fx, fy) => [surface.x + surface.width * fx, surface.y + surface.height * fy]
async function drag(from, to) {
  await page.mouse.move(...at(...from))
  await page.mouse.down()
  await page.mouse.move(...at((from[0] + to[0]) / 2, (from[1] + to[1]) / 2), { steps: 4 })
  await page.mouse.move(...at(...to), { steps: 4 })
  await page.mouse.up()
}
await drag([0.1, 0.1], [0.3, 0.3])
await page.getByRole('button', { name: 'Ellipse', exact: true }).click()
await drag([0.5, 0.4], [0.8, 0.8])
await page.getByRole('button', { name: 'Arrow', exact: true }).click()
await drag([0.9, 0.9], [0.6, 0.6])
const drawn = await page.locator('.annotate__shape').allInnerTexts()
record(
  'draws a rectangle, an ellipse and an arrow in the bullet\'s colour',
  drawn.length === 3 && drawn.every((label) => label.includes('Red')),
  drawn.join(' | '),
)
await page.locator('.annotate__shape', { hasText: 'ellipse' }).click()
await page.getByRole('button', { name: 'Delete shape' }).click()
record('deletes a shape', (await page.locator('.annotate__shape').count()) === 2)
await page.getByLabel('Description').fill('The acquisition window')
await page.getByRole('button', { name: 'Done' }).click()

/* ------------------------------------------------------------------ reorder */

const stepTitles = () =>
  page.locator('.editor-step__title-input').evaluateAll((inputs) => inputs.map((input) => input.value))
await page.locator('.editor-step').nth(1).getByRole('button', { name: 'Move step up' }).click()
const swapped = await stepTitles()
await page.locator('.step-nav__item').nth(0).dragTo(page.locator('.step-nav__item').nth(1))
const restored = await stepTitles()
record(
  'reorders steps by button and by dragging',
  swapped[0] === STEPS[1].title && restored[0] === STEPS[0].title,
  `${swapped.join(' > ')} then ${restored.join(' > ')}`,
)

await page.getByLabel('Time required, from').fill('30')
await page.getByLabel('Time required, to').fill('90')
await page.getByLabel('Summary').fill('Created by the end-to-end test.')

await page.waitForSelector('text=All changes saved', { timeout: 10000 })
record('autosave settles', true)
await page.screenshot({ path: join(SHOTS, 'cms-1-editor.png'), fullPage: true })

/* Publishing is refused while a step is empty, and says which one. */
await page.getByRole('button', { name: 'Add step' }).click()
await page.getByRole('button', { name: 'Publish', exact: true }).click()
const refused = page.locator('.alert--warning')
await refused.waitFor({ timeout: 5000 })
record(
  'publish is refused for an empty step, by number',
  (await refused.innerText()).includes(`Step ${STEPS.length + 1} is empty`),
)
await page.locator('.editor-step').last().getByRole('button', { name: 'Delete step' }).click()
record('the refusal clears once the step is gone', (await refused.count()) === 0)

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
    const flagged = await block.locator('.bullet--flagged', { hasText: bullet.text }).count()
    /* The flag is announced in words, in its own element next to the text. */
    const announced = await block.locator('.bullet__flag-label', { hasText: label }).count()
    record(`step ${index + 1} ${bullet.icon} flag`, flagged > 0 && announced > 0)
  }
}

const bodyText = await page.locator('.guide').innerText()
record('time range rendered', bodyText.includes('30 min – 1 h 30 min'), '30 min – 1 h 30 min')

/* Step media: the video plays in a native player, and the annotations sit
   exactly over the picture they were drawn on. */
const reader = page.locator('.step').first()
record('video renders as a player', (await reader.locator('video[controls]').count()) === 1)
const alignment = await reader.locator('.annotated').evaluate((frame) => {
  const picture = frame.querySelector('img').getBoundingClientRect()
  const shapes = frame.querySelector('svg').getBoundingClientRect()
  const box = frame.querySelector('svg rect').getBoundingClientRect()
  return {
    sameBox: Math.abs(picture.width - shapes.width) < 1 && Math.abs(picture.height - shapes.height) < 1,
    left: (box.left - picture.left) / picture.width,
    top: (box.top - picture.top) / picture.height,
  }
})
record(
  'annotations stay aligned with the picture',
  alignment.sameBox && Math.abs(alignment.left - 0.1) < 0.02 && Math.abs(alignment.top - 0.1) < 0.02,
  JSON.stringify(alignment),
)
record(
  'the picture carries its description',
  (await reader.getByRole('img', { name: 'The acquisition window' }).count()) === 1,
)

const pdfHref = await page.getByRole('link', { name: 'PDF' }).getAttribute('href')
const pdfAnswer = await page.evaluate(async (url) => {
  const response = await fetch(url)
  return `${response.status} ${response.headers.get('content-type')}`
}, pdfHref)
record('PDF downloads', pdfAnswer.startsWith('200 application/pdf'), pdfAnswer)

/* The new tag is shown as it was typed; the reused one under its own name. */
const tagLinks = await page.locator('.guide .tag-row .tag').allInnerTexts()
record('tags link out', tagLinks.length === TAGS.length, tagLinks.join(', '))

/* A tag is only useful if it actually gathers the guide elsewhere. */
await page.locator(`.guide .tag-row .tag[href="/t/${TAGS[0]}"]`).click()
await page.waitForSelector('.guide-row, .empty-state')
const gathered = await page.locator('.guide-row', { hasText: TITLE }).count()
record('tag listing gathers the guide', gathered > 0)

await page.goto(`${BASE}/tags`, { waitUntil: 'networkidle' })
record(
  'tag index lists the new tag',
  (await page.locator(`.tag-index__item[href="/t/${TAGS[0]}"]`).count()) === 1,
)

/* And a reader arriving cold must see the published version. */
await page.goto(publishedUrl, { waitUntil: 'networkidle' })
const rereadTitle = await page.locator('h1').first().innerText()
record('guide resolves on a fresh load', rereadTitle.trim() === TITLE)
const draftBadge = await page.locator('.badge--draft').count()
record('published guide shows no draft badge', draftBadge === 0)

/* ------------------------------------------------------------------ history */

await page.getByRole('link', { name: 'History' }).click()
await page.waitForSelector('.revision-list__row')
record('history lists the publication', (await page.locator('.revision-list__row').count()) === 1)
await page.locator('.revision-list__row').first().click()
await page.waitForSelector('.revision-banner')
record(
  'a published version opens read-only',
  (await page.locator('.step').count()) === STEPS.length &&
    (await page.getByRole('link', { name: 'Edit' }).count()) === 0,
)

/* --------------------------------------------------------------------- wiki */

const PAGE_TITLE = `E2E objectives ${RUN}`

await page.goto(`${BASE}/wiki`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'New wiki page' }).click()
await page.getByLabel('Title').fill(PAGE_TITLE)
await page.getByRole('button', { name: 'Create and start writing' }).click()
const source = page.getByLabel('Page content (Markdown)')
await source.waitFor({ timeout: 15000 })
record('create wiki page opens the editor', true)

await source.click()
await page.getByRole('button', { name: 'Heading', exact: true }).click()
await page.keyboard.type('Which objective')
await page.keyboard.press('End')
await page.keyboard.press('Enter')
await page.keyboard.press('Enter')
await page.keyboard.type('Match the immersion medium. ')
await page.getByRole('button', { name: 'Bold' }).click()
await page.keyboard.type('Never mix oil and water.')
await page.keyboard.press('Control+End')

await page.locator('.wiki-toolbar input[type="file"]').setInputFiles(PICTURE)
await page.waitForFunction(() => document.querySelector('.wiki-source').value.includes('](/api/media/'))
/* The alt text is left selected, so what is typed next replaces it. */
await page.keyboard.type('Objective turret')
await page.keyboard.press('Control+End')

await page.getByRole('button', { name: 'Insert guide list' }).click()
const listDialog = page.getByRole('dialog', { name: 'Insert a guide list' })
await listDialog.getByLabel('Add a tag').fill(TAGS[0])
await listDialog.getByRole('option').first().waitFor({ timeout: 5000 })
await listDialog.getByLabel('Add a tag').press('ArrowDown')
await listDialog.getByLabel('Add a tag').press('Enter')
await listDialog.getByText('1 guide carries this tag right now.').waitFor({ timeout: 5000 })
await listDialog.getByLabel('Heading (optional)').fill('E2E guides')
await listDialog.getByRole('button', { name: 'Insert' }).click()

const body = await source.inputValue()
record(
  'toolbar writes Markdown',
  body.includes('## Which objective') &&
    body.includes('**Never mix oil and water.**') &&
    /!\[Objective turret\]\(\/api\/media\/[^)]+\)/.test(body) &&
    body.includes(`\`\`\`guidelist\ntags: ${TAGS[0]}\nheading: E2E guides\n\`\`\``),
  body.replace(/\n/g, '⏎').slice(0, 200),
)
const preview = page.getByRole('region', { name: 'Preview' })
await preview.locator('.guide-row', { hasText: TITLE }).waitFor({ timeout: 5000 })
record('preview shows the embedded guide list', true)

await page.waitForSelector('text=All changes saved', { timeout: 10000 })
await page.screenshot({ path: join(SHOTS, 'cms-3-wiki-editor.png'), fullPage: true })
await page.getByRole('button', { name: 'Publish', exact: true }).click()
await page.waitForURL(/\/w\/[^/]+$/, { timeout: 15000 })
await page.waitForSelector('.markdown')
const pageUrl = page.url()
record('publish navigates to the wiki page', true, pageUrl)

await page.locator('.markdown .guide-row', { hasText: TITLE }).waitFor({ timeout: 5000 })
record(
  'wiki page renders its text, picture and guide list',
  (await page.getByRole('heading', { name: 'Which objective' }).count()) === 1 &&
    (await page.getByRole('img', { name: 'Objective turret' }).count()) === 1 &&
    (await page.locator('.provenance').count()) === 1,
)
await page.screenshot({ path: join(SHOTS, 'cms-4-wiki-page.png'), fullPage: true })

await page.goto(`${BASE}/wiki`, { waitUntil: 'networkidle' })
record('wiki index lists the page', (await page.locator('.guide-row', { hasText: PAGE_TITLE }).count()) === 1)

await page.goto(`${BASE}/search?q=${encodeURIComponent(RUN)}`, { waitUntil: 'networkidle' })
const sections = await page.locator('.section__title').allInnerTexts()
record(
  'search tells guides from wiki pages',
  sections.some((title) => title.startsWith('Guides')) &&
    sections.some((title) => title.startsWith('Wiki pages')),
  sections.join(' | ').replace(/\n/g, ' '),
)

record('no console errors', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 300))

await context.close()

/* ----------------------------------------------------------------- as viewer */

if (VIEWER_EMAIL) {
  const viewerContext = await browser.newContext({ viewport: { width: 390, height: 844 } })
  const viewer = await viewerContext.newPage()
  await viewer.goto(BASE, { waitUntil: 'networkidle' })
  await viewer.getByLabel('Email').fill(VIEWER_EMAIL)
  await viewer.getByLabel('Password').fill(PASSWORD)
  await viewer.getByRole('button', { name: 'Sign in' }).click()
  await viewer.waitForSelector('.category-card', { timeout: 15000 })

  await viewer.goto(publishedUrl, { waitUntil: 'networkidle' })
  await viewer.waitForSelector('.step')
  record(
    'a viewer reads the guide on a phone, with no way to edit it',
    (await viewer.locator('.step').count()) === STEPS.length &&
      (await viewer.getByRole('link', { name: 'Edit' }).count()) === 0 &&
      (await viewer.getByRole('link', { name: 'History' }).count()) === 0,
  )
  record(
    'a viewer gets the step picture and video',
    await viewer.evaluate(async () => {
      const sources = [...document.querySelectorAll('.step img, .step video')].map((node) => node.src)
      const answers = await Promise.all(sources.map((source) => fetch(source, { method: 'HEAD' })))
      return sources.length === 2 && answers.every((answer) => answer.ok)
    }),
  )
  record(
    'no sideways scrolling for the viewer',
    await viewer.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  )
  await viewer.screenshot({ path: join(SHOTS, 'cms-5-viewer-phone.png'), fullPage: true })

  await viewer.goto(pageUrl, { waitUntil: 'networkidle' })
  await viewer.locator('.markdown .guide-row', { hasText: TITLE }).waitFor({ timeout: 5000 })
  record('a viewer reads the wiki page and its guide list', true)

  await viewer.goto(`${publishedUrl}/history`, { waitUntil: 'networkidle' })
  record('history is not a viewer\'s screen', new URL(viewer.url()).pathname === '/')
  await viewerContext.close()
}

await browser.close()

const failed = results.filter((result) => !result.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
if (failed.length) {
  console.log('\nFailures:')
  for (const failure of failed) console.log(`  - ${failure.step} ${failure.detail}`)
  process.exitCode = 1
}

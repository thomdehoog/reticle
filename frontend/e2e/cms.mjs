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

for (const tag of TAGS) {
  await page.getByLabel('Add a tag').fill(tag)
  await page.getByLabel('Add a tag').press('Enter')
}
const chipCount = await page.locator('.tag-input__chips .tag').count()
record('add tags', chipCount === TAGS.length, `${chipCount} chips`)

await page.getByLabel('Time required, from').fill('30')
await page.getByLabel('Time required, to').fill('90')
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

const bodyText = await page.locator('.guide').innerText()
record('time range rendered', bodyText.includes('30 min – 1 h 30 min'), '30 min – 1 h 30 min')

for (const tag of TAGS) {
  const link = page.getByRole('link', { name: tag })
  record(`tag ${tag} links out`, (await link.count()) > 0)
}

/* A tag is only useful if it actually gathers the guide elsewhere. */
await page.getByRole('link', { name: TAGS[0] }).click()
await page.waitForSelector('.guide-row, .empty-state')
const gathered = await page.locator('.guide-row', { hasText: TITLE }).count()
record('tag listing gathers the guide', gathered > 0)

/* And a reader arriving cold must see the published version. */
await page.goto(publishedUrl, { waitUntil: 'networkidle' })
const rereadTitle = await page.locator('h1').first().innerText()
record('guide resolves on a fresh load', rereadTitle.trim() === TITLE)
const draftBadge = await page.locator('.badge--draft').count()
record('published guide shows no draft badge', draftBadge === 0)

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

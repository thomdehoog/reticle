/**
 * Browser smoke test for a running Reticle stack.
 *
 * Unit tests prove the pieces behave; this proves the assembled thing actually
 * renders and can be used. It drives real Chromium through the paths that
 * matter — sign in, read a guide, open the editor — at desktop, tablet and
 * phone widths, and fails on console errors or sideways scrolling.
 *
 * Requires the backend on :8000 and the dev server on :5173, and an account
 * matching RETICLE_E2E_EMAIL / RETICLE_E2E_PASSWORD. RETICLE_E2E_BASE points it
 * at another address, and RETICLE_E2E_CHROMIUM at a Chromium binary when
 * Playwright's own download is not the one installed.
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
  console.error('Set RETICLE_E2E_EMAIL and RETICLE_E2E_PASSWORD before running the smoke test.')
  process.exit(2)
}

const VIEWPORTS = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'phone', width: 390, height: 844 },
]

const results = []

function record(step, ok, detail = '') {
  results.push({ step, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`)
}

const browser = await chromium.launch({
  executablePath: process.env.RETICLE_E2E_CHROMIUM || undefined,
})

for (const viewport of VIEWPORTS) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
  })
  const page = await context.newPage()

  const consoleErrors = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(String(error)))

  await page.goto(BASE, { waitUntil: 'networkidle' })

  const signIn = page.getByRole('button', { name: 'Sign in' })
  record(`[${viewport.name}] login screen renders`, await signIn.isVisible())
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-1-login.png`), fullPage: true })

  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await signIn.click()

  await page.waitForSelector('.category-card', { timeout: 15000 })
  const categories = await page.locator('.category-card').count()
  record(`[${viewport.name}] home lists categories`, categories > 0, `${categories} cards`)
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-2-home.png`), fullPage: true })

  /**
   * Signing in legitimately produces a 401: the app asks who it is talking to
   * before it has a session. That one is expected, so the console watch starts
   * clean here and anything recorded from now on is a genuine fault.
   */
  consoleErrors.length = 0

  /**
   * Matched on the card's name element, not the card: "Sample Preparation" is
   * described as "Preparing samples for light microscopy", so a substring match
   * against the whole card opens the wrong category.
   */
  await page
    .locator('.category-card')
    .filter({ has: page.locator('.category-card__name', { hasText: /^Light Microscopy$/ }) })
    .first()
    .click()
  await page.waitForSelector('.guide-row, .empty-state')
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-3-category.png`), fullPage: true })

  /* The title, not the row: a row also carries tag chips, and on a phone the
     middle of a row is as likely to be one of those. */
  const guideRow = page.locator('.guide-row__title').first()
  if (await guideRow.count()) {
    await guideRow.click()
    await page.waitForSelector('.step')
    const steps = await page.locator('.step').count()
    record(`[${viewport.name}] guide renders steps`, steps > 0, `${steps} steps`)
    await page.screenshot({ path: join(SHOTS, `${viewport.name}-4-guide.png`), fullPage: true })

    const edit = page.getByRole('link', { name: 'Edit' })
    if (await edit.count()) {
      await edit.click()
      await page.waitForSelector('.editor-step')
      const editorSteps = await page.locator('.editor-step').count()
      record(`[${viewport.name}] editor opens`, editorSteps > 0, `${editorSteps} step cards`)
      await page.screenshot({ path: join(SHOTS, `${viewport.name}-5-editor.png`), fullPage: true })
    }
  } else {
    record(`[${viewport.name}] guide renders steps`, false, 'no guides in Light Microscopy')
  }

  /**
   * The ways in that are not the category tree: the tag index, a tag, the wiki
   * index and a wiki page. Every screen visited from here on is also checked
   * for sideways scrolling, which is the commonest way a new screen breaks on
   * a phone.
   */
  const overflowing = []
  async function checkWidth(name) {
    const overflows = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    )
    if (overflows) overflowing.push(name)
  }
  await checkWidth('editor or guide')

  const nav = page.getByRole('navigation', { name: 'Main' })

  await nav.getByRole('link', { name: 'Tags' }).click()
  await page.waitForSelector('.tag-index__item, .empty-state')
  const tags = await page.locator('.tag-index__item').count()
  record(`[${viewport.name}] tag index lists tags`, tags > 0, `${tags} tags`)
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-6-tags.png`), fullPage: true })
  await checkWidth('tags')

  if (tags > 0) {
    await page.locator('.tag-index__item').first().click()
    await page.waitForSelector('.guide-row, .empty-state')
    const tagged = await page.locator('.guide-row').count()
    record(`[${viewport.name}] a tag gathers its guides`, tagged > 0, `${tagged} guides`)
    await checkWidth('tag')

    /* A reader's guide, reached through a tag: the PDF must be a real file. */
    /* A published one: a draft has no history to list further down. */
    await page.locator('.guide-row:not(:has(.badge)) .guide-row__title').first().click()
    await page.waitForSelector('.guide__meta')
    const pdf = page.getByRole('link', { name: 'PDF' })
    const href = await pdf.getAttribute('href')
    const answer = await page.evaluate(async (url) => {
      const response = await fetch(url)
      return `${response.status} ${response.headers.get('content-type')}`
    }, href)
    record(
      `[${viewport.name}] PDF link downloads a PDF`,
      (await pdf.getAttribute('download')) !== null && answer.startsWith('200 application/pdf'),
      answer,
    )
    await checkWidth('guide')

    /* History is an author's screen; a viewer account simply skips it. */
    const history = page.getByRole('link', { name: 'History' })
    if (await history.count()) {
      await history.click()
      await page.waitForSelector('.revision-list, .empty-state')
      const versions = await page.locator('.revision-list__row').count()
      record(`[${viewport.name}] history lists versions`, versions > 0, `${versions} versions`)
      await page.screenshot({ path: join(SHOTS, `${viewport.name}-7-history.png`), fullPage: true })
      await checkWidth('history')

      if (versions > 0) {
        await page.locator('.revision-list__row').last().click()
        await page.waitForSelector('.revision-banner')
        const banner = await page.locator('.revision-banner').innerText()
        record(`[${viewport.name}] a past version is bannered`, /Version \d+, published/.test(banner))
        await page.screenshot({ path: join(SHOTS, `${viewport.name}-8-version.png`), fullPage: true })
        await checkWidth('version')
      }
    }
  }

  await nav.getByRole('link', { name: 'Wiki' }).click()
  await page.waitForSelector('.guide-row, .empty-state')
  const pages = await page.locator('.guide-row').count()
  record(`[${viewport.name}] wiki index lists pages`, pages > 0, `${pages} pages`)
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-9-wiki.png`), fullPage: true })
  await checkWidth('wiki')

  if (pages > 0) {
    await page.locator('.guide-row__title').first().click()
    await page.waitForSelector('.markdown')
    record(`[${viewport.name}] a wiki page renders`, (await page.locator('.provenance').count()) > 0)
    await page.screenshot({ path: join(SHOTS, `${viewport.name}-10-page.png`), fullPage: true })
    await checkWidth('wiki page')
  }

  record(
    `[${viewport.name}] no horizontal overflow`,
    overflowing.length === 0,
    overflowing.join(', '),
  )

  record(
    `[${viewport.name}] no console errors`,
    consoleErrors.length === 0,
    consoleErrors.join(' | ').slice(0, 300),
  )

  await context.close()
}

await browser.close()

const failed = results.filter((result) => !result.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
console.log(`screenshots: ${SHOTS}`)
if (failed.length) process.exitCode = 1

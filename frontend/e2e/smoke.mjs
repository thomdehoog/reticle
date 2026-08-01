/**
 * Browser smoke test for a running Reticle stack.
 *
 * Unit tests prove the pieces behave; this proves the assembled thing actually
 * renders and can be used. It drives real Chromium through the paths that
 * matter — sign in, read a guide, open the editor — at desktop, tablet and
 * phone widths, and fails on console errors or sideways scrolling.
 *
 * Requires the backend on :8000 and the dev server on :5173, and an account
 * matching RETICLE_E2E_EMAIL / RETICLE_E2E_PASSWORD.
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

  await page.waitForSelector('.tile', { timeout: 15000 })
  const categories = await page.locator('.tile').count()
  record(`[${viewport.name}] home lists categories`, categories > 0, `${categories} cards`)
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-2-home.png`), fullPage: true })

  /**
   * Signing in legitimately produces a 401: the app asks who it is talking to
   * before it has a session, twice over because StrictMode double-invokes the
   * effect in dev. Those are expected, so the console watch starts clean here
   * and anything recorded from now on is a genuine fault.
   */
  consoleErrors.length = 0

  /**
   * Matched on the card's name element, not the card: "Sample Preparation" is
   * described as "Preparing samples for light microscopy", so a substring match
   * against the whole card opens the wrong category.
   */
  /* Armed before the click, not after: a response that arrives while the
     listener is still being attached is a response nobody was waiting for. */
  const listing = page.waitForResponse(
    (response) => response.url().includes('/api/guides?categoryId='),
    { timeout: 15000 },
  )

  await page
    .locator('.tile')
    .filter({ has: page.locator('.tile__name', { hasText: /^Light Microscopy$/ }) })
    .first()
    .click()
  /* Three waits look right here and are not.
     "networkidle" fires immediately, because a client-side route change has
     nothing in flight at the moment of the click. Waiting for the spinner to
     detach can resolve before the spinner has been rendered at all. And
     ".tile--guide, .empty-state" is satisfied by the empty state a guide-list
     embedded in the landing page shows while it is still fetching, which is
     not the category's own list.
     Waiting for the response that carries the list is the thing that actually
     means the data is here. */
  await listing
  await page.waitForSelector('.tile--guide, .empty-state')
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-3-category.png`), fullPage: true })

  const guideRow = page.locator('.tile--guide').first()
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

  const overflows = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth + 1,
  )
  record(`[${viewport.name}] no horizontal overflow`, !overflows)

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

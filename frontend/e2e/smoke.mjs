/**
 * Browser smoke test for a running Reticle stack.
 *
 * Unit tests prove the pieces behave; this proves the assembled thing actually
 * renders and can be used. It drives real Chromium through the paths that
 * matter — sign in, read a guide, open the editor — at desktop, tablet and
 * phone widths, and fails on console errors or sideways scrolling.
 *
 * It also measures the phone. Reticle is read one-handed at an instrument, so
 * every screen is checked for text too small to read at arm's length in a dark
 * room and for controls too small to hit with a thumb. Those are the two things
 * a desk-sized browser window will never show you, and they come back one
 * declaration at a time unless something fails on them.
 *
 * The narrow viewport is 320px rather than a modern phone's 390: a layout that
 * survives 320 survives everything, and plenty of phones still report that many
 * CSS pixels. It runs with `hasTouch` and `isMobile` so that `@media (hover:
 * none)` rules — which is where the larger touch targets live — apply as they
 * will in the reader's hand.
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
  { name: 'desktop', width: 1440, height: 900, touch: false },
  { name: 'tablet', width: 768, height: 1024, touch: true },
  { name: 'phone', width: 320, height: 568, touch: true },
]

/** WCAG 2.2 Target Size (Minimum). 44px is the aim; this is the floor. */
const MINIMUM_TARGET_PX = 24

const MINIMUM_TEXT_PX = 12

const results = []

function record(step, ok, detail = '') {
  results.push({ step, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`)
}

/**
 * Everything on the current screen that is too small to read or to hit.
 *
 * Runs inside the page because both answers are rendered facts: a target's
 * height comes from padding and line-height as much as from any rule, and a
 * font size given in `em` is not knowable until it has a parent. Text is read
 * off leaf elements only, so a paragraph is not blamed for the size of a span
 * inside it.
 */
function measureReadability(page) {
  return page.evaluate(
    ({ minTarget, minText }) => {
      const targets = new Set()
      for (const element of document.querySelectorAll(
        'button, a, input, select, textarea, summary, [role="button"]',
      )) {
        const box = element.getBoundingClientRect()
        /* Nothing rendered has no size to answer for: a control inside a closed
           menu is not on the screen yet. */
        if (box.width === 0 && box.height === 0) continue
        if (element.type === 'hidden') continue
        if (box.width < minTarget || box.height < minTarget) {
          const name = (element.getAttribute('aria-label') ?? element.textContent ?? '').trim()
          targets.add(
            `${element.tagName.toLowerCase()}.${element.className.toString().split(' ')[0]} "${name.slice(0, 20)}" ${Math.round(box.width)}x${Math.round(box.height)}`,
          )
        }
      }

      const text = new Set()
      for (const element of document.querySelectorAll('*')) {
        if (element.children.length > 0) continue
        if ((element.textContent ?? '').trim() === '') continue
        const style = getComputedStyle(element)
        if (style.display === 'none' || style.visibility === 'hidden') continue
        const size = parseFloat(style.fontSize)
        if (size < minText) {
          text.add(
            `${element.tagName.toLowerCase()}.${element.className.toString().split(' ')[0]} ${size}px`,
          )
        }
      }

      return { targets: [...targets], text: [...text] }
    },
    { minTarget: MINIMUM_TARGET_PX, minText: MINIMUM_TEXT_PX },
  )
}

/** Records both floors for one screen, naming what broke them. */
async function checkReadability(page, viewport, screen) {
  const { targets, text } = await measureReadability(page)
  record(
    `[${viewport.name}] ${screen}: every control is at least ${MINIMUM_TARGET_PX}px`,
    targets.length === 0,
    targets.join(' | ').slice(0, 400),
  )
  record(
    `[${viewport.name}] ${screen}: no text under ${MINIMUM_TEXT_PX}px`,
    text.length === 0,
    text.join(' | ').slice(0, 400),
  )
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
    hasTouch: viewport.touch,
    isMobile: viewport.touch,
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
  await checkReadability(page, viewport, 'home')

  /* One row, on every screen in the application. Wrapped, it took 233px of a
     568px phone before any content at all. */
  const headerHeight = await page
    .locator('.app__header')
    .evaluate((element) => Math.round(element.getBoundingClientRect().height))
  record(`[${viewport.name}] the header is one row`, headerHeight <= 64, `${headerHeight}px`)

  /* With the menu open too, because on a phone that panel holds every link and
     every action in the application and is only measurable while it is up. */
  const menu = page.getByRole('button', { name: 'Menu' })
  if (await menu.isVisible()) {
    await menu.click()
    await page.waitForSelector('.menu-sheet')
    await checkReadability(page, viewport, 'menu')
    /* Escape rather than the button again: the sheet is a dialog over the page,
       so its backdrop is what a click at the button's position would land on. */
    await page.keyboard.press('Escape')
    await page.waitForSelector('.menu-sheet', { state: 'detached' })
  }

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
     ".guide-row, .empty-state" is satisfied by the empty state a guide-list
     embedded in the landing page shows while it is still fetching, which is
     not the category's own list.
     Waiting for the response that carries the list is the thing that actually
     means the data is here. */
  await listing
  await page.waitForSelector('.tile, .guide-row, .empty-state')
  await page.screenshot({ path: join(SHOTS, `${viewport.name}-3-category.png`), fullPage: true })
  await checkReadability(page, viewport, 'category')

  /**
   * Each level of the tree shows one thing, so a category with sub-categories
   * shows those and no guides at all. The guides are one level down, which is
   * where the rest of this walk has to go to find one.
   */
  /* Named by what it is not: the wiki cards further down the page are tiles
     too, and clicking one of those leads to an article rather than to guides. */
  const subSection = page.locator('.tile:not(.tile--wiki):not(.tile--guide)').first()
  if (await subSection.count()) {
    await subSection.click()
    await page.waitForSelector('.guide-row, .empty-state')
    await checkReadability(page, viewport, 'sub-category')
  }

  const guideRow = page.locator('.guide-row').first()
  if (await guideRow.count()) {
    await guideRow.click()
    await page.waitForSelector('.step')
    const steps = await page.locator('.step').count()
    record(`[${viewport.name}] guide renders steps`, steps > 0, `${steps} steps`)
    await page.screenshot({ path: join(SHOTS, `${viewport.name}-4-guide.png`), fullPage: true })
    await checkReadability(page, viewport, 'guide')

    /**
     * The point of the whole exercise: nothing but the guide's own front matter
     * stands between the top of the screen and step 1.
     *
     * Measured as "the section list is not above step 1" rather than "step 1 is
     * in the first screenful", because how far down step 1 lands also depends on
     * how long its author made the introduction — which is content, and not this
     * test's business.
     *
     * Where the list is a column beside the guide rather than a block stacked
     * above it, the question does not arise: it is not in the reader's way, it
     * is next to them. That is detected from the boxes rather than from a width,
     * so the check follows the stylesheet's breakpoint wherever it moves to.
     */
    const stepOrder = await page.evaluate(() => {
      const nav = document.querySelector('.section-nav')
      const step = document.querySelector('.step')
      if (!nav || !step) return { stacked: false, navAbove: false }
      const navBox = nav.getBoundingClientRect()
      const stepBox = step.getBoundingClientRect()
      return {
        stacked: navBox.right > stepBox.left,
        navAbove: navBox.top < stepBox.top,
      }
    })
    if (stepOrder.stacked) {
      record(`[${viewport.name}] the section list does not precede step 1`, !stepOrder.navAbove)
    }

    /* What the reader actually scrolls past to reach the first instruction. */
    const stepTop = await page.evaluate(() => {
      const step = document.querySelector('.step')
      return step ? Math.round(step.getBoundingClientRect().top + window.scrollY) : -1
    })
    record(`[${viewport.name}] step 1 begins at ${stepTop}px`, stepTop > 0)

    const edit = page.getByRole('link', { name: 'Edit' })
    if (await edit.count()) {
      await edit.click()
      await page.waitForSelector('.editor-step')
      const editorSteps = await page.locator('.editor-step').count()
      record(`[${viewport.name}] editor opens`, editorSteps > 0, `${editorSteps} step cards`)
      await page.screenshot({ path: join(SHOTS, `${viewport.name}-5-editor.png`), fullPage: true })
      await checkReadability(page, viewport, 'editor')
    }
  } else {
    record(`[${viewport.name}] guide renders steps`, false, 'no guides in Light Microscopy')
  }

  /*
   * The screens the walk above never reaches.
   *
   * Home, a category, a guide and the editor are the reader's path and are
   * checked in depth. These seven are checked only for being reachable and
   * readable — but that is the difference between an administrator finding a
   * 500 and a reader finding one. Every screen in the application is now
   * visited by something.
   *
   * The wiki page and the tag are looked up rather than named, because a
   * hard-coded slug stops failing the day it is renamed: it 404s, the page
   * renders its empty state, and the check passes against nothing.
   */
  const reachable = await page.evaluate(async () => {
    const get = async (u) => (await fetch(u, { credentials: 'same-origin' })).json()
    const [pages, tags] = await Promise.all([get('/api/pages'), get('/api/tags')])
    return { page: pages[0]?.slug ?? null, tag: tags[0]?.slug ?? null }
  })

  const rest = [
    ['wiki index', '/w'],
    ['tags', '/t'],
    ['search', '/search?q=laser'],
    ['account', '/account'],
    ['categories admin', '/categories'],
    ['people admin', '/users'],
    ...(reachable.page ? [['wiki page', `/w/${reachable.page}`]] : []),
    ...(reachable.tag ? [['tag', `/t/${encodeURIComponent(reachable.tag)}`]] : []),
  ]

  for (const [name, path] of rest) {
    await page.goto(BASE + path, { waitUntil: 'networkidle' })

    /*
     * Not "did it respond" and not "did it draw something". In a single-page
     * application every path returns 200 — the server hands back the same
     * document whatever you ask for — and a route that matches nothing still
     * draws a tidy "that does not exist" panel. Both of those pass while the
     * screen is broken; a run against a deliberately wrong path proved it.
     *
     * So the check is: this screen put its own heading up, and nothing on it is
     * an error or an apology.
     */
    const state = await page.evaluate(() => {
      const main = document.querySelector('.app__main')
      return {
        heading: main?.querySelector('h1')?.textContent?.trim() ?? '',
        text: main?.textContent ?? '',
        alerts: main?.querySelectorAll('.alert--error, .empty-state').length ?? 0,
      }
    })
    record(`[${viewport.name}] ${name} has a heading`, state.heading.length > 0, state.heading)
    record(
      `[${viewport.name}] ${name} is not an error`,
      state.alerts === 0 && !/does not exist|went wrong|not found/i.test(state.text),
    )
    await checkReadability(page, viewport, name)
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

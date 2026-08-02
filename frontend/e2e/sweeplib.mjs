/**
 * Shared browser driver for the audits under this directory.
 *
 * Opens Chromium at a given width, signs in, collects console errors and
 * failed requests as it goes, and writes screenshots to /var/tmp/sweep. It is
 * deliberately outside the vitest suites: these run against a live stack —
 * real server, real database, real pictures — which is the only way to measure
 * a rendered layout, and is too slow and too stateful to sit in a unit run.
 *
 * Configured entirely from the environment, so it points at a staging
 * deployment as readily as at localhost:
 *
 *     SWEEP_BASE=… SWEEP_EMAIL=… SWEEP_PASSWORD=… node e2e/layout-audit.mjs
 */
import { chromium } from 'playwright'
import { mkdirSync, appendFileSync } from 'node:fs'

export const BASE = process.env.SWEEP_BASE ?? 'http://localhost:5175'
export const EMAIL = process.env.SWEEP_EMAIL ?? 'thom@zmb.uzh.ch'
export const PASSWORD = process.env.SWEEP_PASSWORD ?? 'demo-password-not-real'
export const SHOTS = '/var/tmp/sweep'
mkdirSync(SHOTS, { recursive: true })

export const faults = []
export const results = []

export function record(step, ok, detail = '') {
  results.push({ step, ok, detail })
  const line = `${ok ? 'PASS' : 'FAIL'}  ${step}${detail ? ' — ' + detail : ''}`
  console.log(line)
}

export function note(msg) {
  console.log(`      ${msg}`)
}

/** Attaches console + network listeners that collect anything worth reporting. */
export function watch(page, label = '') {
  page.on('console', (msg) => {
    if (msg.type() !== 'error' && msg.type() !== 'warning') return
    /* The browser's own resource errors say only "failed to load", and the one
       thing worth knowing — which resource — lives in the message's location.
       Without it a stray 404 costs an hour to trace back to a favicon. */
    const source = msg.location()?.url
    const text = msg.text() + (source ? ` (${source})` : '')
    faults.push({ kind: 'console', level: msg.type(), text, where: label + ' ' + page.url() })
  })
  page.on('pageerror', (err) => {
    faults.push({ kind: 'pageerror', text: String(err), where: label + ' ' + page.url() })
  })
  page.on('response', (res) => {
    const s = res.status()
    if (s < 400) return
    const url = res.url()
    // /api/auth/me returning 401 before sign-in is expected.
    if (s === 401 && url.includes('/api/auth/me')) return
    faults.push({ kind: 'http', status: s, text: `${res.request().method()} ${url}`, where: label })
  })
}

export async function open({ width = 1440, height = 900, touch = false } = {}) {
  const browser = await chromium.launch({
    executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
    args: ['--no-sandbox', '--force-color-profile=srgb'],
  })
  const context = await browser.newContext({
    viewport: { width, height },
    hasTouch: touch,
    isMobile: touch,
    deviceScaleFactor: 1,
  })
  const page = await context.newPage()
  watch(page)
  return { browser, context, page }
}

export async function login(page) {
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded' })
  // Already signed in?
  if (await page.locator('.app').count()) return
  await page.locator('#email, input[type=email]').first().fill(EMAIL)
  await page.locator('#password, input[type=password]').first().fill(PASSWORD)
  await page.locator('button[type=submit]').first().click()
  await page.waitForSelector('.app', { timeout: 15000 })
}

/**
 * Screenshot the current page, full page.
 *
 * Scrolls the whole document first: thumbnails are `loading="lazy"`, and a
 * fullPage capture does not itself trigger them, so an un-scrolled shot shows
 * blank boxes for everything below the fold and invents defects that are not
 * there. `keepScroll` leaves the viewport where it was for shots of a control
 * that has to stay in view.
 */
export async function shot(page, name, { keepScroll = false } = {}) {
  const file = `${SHOTS}/${name}.png`
  if (!keepScroll) {
    await page.evaluate(async () => {
      const y0 = window.scrollY
      for (let y = 0; y < document.body.scrollHeight; y += 400) {
        window.scrollTo(0, y)
        await new Promise((r) => setTimeout(r, 40))
      }
      window.scrollTo(0, y0)
    })
    await page.waitForTimeout(600)
  }
  await page.screenshot({ path: file, fullPage: true })
  return file
}

export function dumpFaults(tag) {
  if (faults.length === 0) {
    console.log(`\n== no console/network faults (${tag}) ==`)
    return
  }
  console.log(`\n== faults (${tag}) ==`)
  const seen = new Set()
  for (const f of faults) {
    const key = f.kind + f.text
    if (seen.has(key)) continue
    seen.add(key)
    console.log(`  [${f.kind}${f.status ? ' ' + f.status : ''}] ${f.text}  @ ${f.where}`)
  }
  appendFileSync(`${SHOTS}/faults.log`, JSON.stringify({ tag, faults }, null, 1) + '\n')
}

export function summary(tag) {
  const bad = results.filter((r) => !r.ok)
  console.log(`\n== ${tag}: ${results.length - bad.length}/${results.length} passed ==`)
  for (const b of bad) console.log(`  FAIL ${b.step} — ${b.detail}`)
}

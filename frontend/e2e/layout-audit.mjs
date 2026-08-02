/**
 * A measured layout audit, run against a live stack.
 *
 * Looks for the things a screenshot shows but no assertion catches: content
 * wider than the window, an element spilling out of the box that is supposed to
 * contain it, text clipped by an ancestor's overflow, and controls that overlap
 * each other or sit off-screen. It found the page editor's Remove button
 * sitting 65px past the right edge of a 1440px window, which every unit test
 * and the smoke test had passed over.
 *
 * Kept, unlike the scripted click-throughs it was written beside, because it
 * asserts a property rather than replaying a sequence: a walkthrough that
 * clicks forty named controls in order is a thousand lines that rot the first
 * time a label changes, and this is one rule applied to every route.
 *
 *     SWEEP_W=390 SWEEP_EMAIL=… SWEEP_PASSWORD=… node e2e/layout-audit.mjs
 */
import { open, login, record, note, dumpFaults, summary, BASE } from './sweeplib.mjs'

const W = Number(process.env.SWEEP_W ?? 1440)
const TAG = process.env.SWEEP_TAG ?? 'L'

const { browser, page } = await open({ width: W, height: 900, touch: W < 800 })

/**
 * The two editor routes need real identifiers, and asking the API for them is
 * the only honest way to get one.
 *
 * They used to come from the environment, and when nothing set them the audit
 * cheerfully measured `/g/undefined/edit` — a page that had failed to load —
 * and reported every check passed. An audit that examines a broken page and
 * calls it clean is worse than no audit.
 */
async function editableIds(page) {
  return page.evaluate(async () => {
    const get = async (u) => (await fetch(u, { credentials: 'same-origin' })).json()
    const [guides, pages] = await Promise.all([get('/api/guides'), get('/api/pages')])
    return { guide: guides[0]?.id ?? null, page: pages[0]?.id ?? null }
  })
}

const PATHS = [
  ['/', 'home'],
  ['/c/basics-access-and-it', 'category'],
  ['/c/light-microscopy', 'category-parent'],
  ['/g/starting-a-session-on-the-confocal', 'guide'],
  ['/w', 'wiki-index'],
  ['/w/light-microscopy', 'wiki-page'],
  ['/t', 'tags'],
  ['/t/confocal', 'tag'],
  ['/search?q=confocal', 'search-hit'],
  ['/search?q=zzzznotathing', 'search-miss'],
  ['/search', 'search-empty'],
  ['/account', 'account'],
  ['/categories', 'categories-admin'],
  ['/users', 'users-admin'],
]

/** Everything measurable that looks wrong on the page as rendered. */
function audit() {
  return page.evaluate(() => {
    const problems = []
    const docWidth = document.documentElement.clientWidth

    /* `.visually-hidden` is a 1px clipped box on purpose — that is how text is
       given to a screen reader and kept off the screen. Measuring it as clipped
       or off-window reports the technique, not a defect. */
    const hidden = (el) => el.closest?.('.visually-hidden') != null

    // 1. anything sticking out of the window
    for (const el of document.querySelectorAll('body *')) {
      if (hidden(el)) continue
      const s = getComputedStyle(el)
      if (s.display === 'none' || s.visibility === 'hidden' || s.position === 'fixed') continue
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      if (r.right > docWidth + 1 || r.left < -1) {
        problems.push({
          kind: 'off-screen',
          el: el.tagName + '.' + (typeof el.className === 'string' ? el.className : ''),
          detail: `left=${Math.round(r.left)} right=${Math.round(r.right)} doc=${docWidth}`,
          text: (el.textContent ?? '').trim().slice(0, 60),
        })
      }
    }

    // 2. text clipped by an ancestor that hides its overflow
    for (const el of document.querySelectorAll('p, h1, h2, h3, h4, span, a, li, td, th, div, label')) {
      if (el.children.length > 0 || hidden(el)) continue
      const text = (el.textContent ?? '').trim()
      if (text === '') continue
      const s = getComputedStyle(el)
      if (s.display === 'none' || s.visibility === 'hidden') continue
      // scrollWidth beyond clientWidth with hidden overflow and no ellipsis
      if (
        el.scrollWidth > el.clientWidth + 1 &&
        s.overflowX === 'hidden' &&
        s.textOverflow !== 'ellipsis'
      ) {
        problems.push({
          kind: 'clipped-text',
          el: el.tagName + '.' + (typeof el.className === 'string' ? el.className : ''),
          detail: `scrollWidth=${el.scrollWidth} clientWidth=${el.clientWidth}`,
          text: text.slice(0, 60),
        })
      }
    }

    // 3. a control whose centre belongs to something else — i.e. covered
    for (const el of document.querySelectorAll('button, a[href], input, select, textarea')) {
      if (hidden(el)) continue
      const s = getComputedStyle(el)
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') continue
      const r = el.getBoundingClientRect()
      if (r.width === 0 || r.height === 0) continue
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) continue
      const hit = document.elementFromPoint(cx, cy)
      if (!hit) continue
      if (hit !== el && !el.contains(hit) && !hit.contains(el)) {
        problems.push({
          kind: 'covered-control',
          el: el.tagName + '.' + (typeof el.className === 'string' ? el.className : '') +
            (el.getAttribute('aria-label') ? ` [${el.getAttribute('aria-label')}]` : ''),
          detail: `covered by ${hit.tagName}.${typeof hit.className === 'string' ? hit.className : ''}`,
          text: (el.textContent ?? '').trim().slice(0, 40),
        })
      }
    }

    // 4. an image that is badly out of its natural proportions
    for (const img of document.querySelectorAll('img')) {
      const r = img.getBoundingClientRect()
      if (r.width === 0 || img.naturalWidth === 0) continue
      const natural = img.naturalWidth / img.naturalHeight
      const shown = r.width / r.height
      const fit = getComputedStyle(img).objectFit
      if (fit === 'cover' || fit === 'contain') continue
      const skew = Math.max(natural / shown, shown / natural)
      if (skew > 1.15) {
        problems.push({
          kind: 'stretched-image',
          el: 'IMG.' + (typeof img.className === 'string' ? img.className : ''),
          detail: `natural ${img.naturalWidth}x${img.naturalHeight} (${natural.toFixed(2)}), shown ${Math.round(r.width)}x${Math.round(r.height)} (${shown.toFixed(2)}), object-fit:${fit}`,
          text: img.getAttribute('src') ?? '',
        })
      }
    }

    // 5. an image that failed to load with nothing in its place
    for (const img of document.querySelectorAll('img')) {
      if (img.complete && img.naturalWidth === 0) {
        problems.push({
          kind: 'broken-image',
          el: 'IMG.' + (typeof img.className === 'string' ? img.className : ''),
          detail: 'loaded but has no pixels; no fallback',
          text: img.getAttribute('src') ?? '',
        })
      }
    }

    return {
      problems,
      horizontalScroll: document.documentElement.scrollWidth > docWidth + 1,
      scrollWidth: document.documentElement.scrollWidth,
      docWidth,
    }
  })
}

/**
 * Did this route actually render, or is it an error page?
 *
 * Without this the audit is circular: a route that failed to load has no boxes
 * to measure, so nothing sticks out of the window and every check passes. The
 * two conditions are the same pair the smoke test settled on — a heading means
 * a screen was drawn, and the absence of the error surface means it was the
 * screen that was asked for.
 *
 * It looks inside `main` only. The side rail carries its own headings, and they
 * are there on every route including one that rendered nothing — so a
 * document-wide query would have made the check pass on exactly the pages it
 * exists to catch.
 */
async function rendered(page) {
  return page.evaluate(() => {
    const heading = document.querySelector('main h1, main h2')?.textContent?.trim() ?? ''
    const failed = document.querySelector('.error, .not-found') != null
    return { heading, failed }
  })
}

try {
  await login(page)

  const ids = await editableIds(page)
  record('found a guide to edit', ids.guide != null)
  record('found a page to edit', ids.page != null)
  const routes = [
    ...PATHS,
    ...(ids.guide ? [[`/g/${ids.guide}/edit`, 'guide-editor']] : []),
    ...(ids.page ? [[`/w/${ids.page}/edit`, 'page-editor']] : []),
  ]

  for (const [path, name] of routes) {
    await page.goto(BASE + path, { waitUntil: 'domcontentloaded' })
    await page.waitForTimeout(900)
    await page.evaluate(async () => {
      for (let y = 0; y < document.body.scrollHeight; y += 400) {
        window.scrollTo(0, y)
        await new Promise((r) => setTimeout(r, 40))
      }
      window.scrollTo(0, 0)
    })
    await page.waitForTimeout(700)

    const { heading, failed } = await rendered(page)
    if (heading === '' || failed) {
      record(`${name}: rendered`, false, failed ? 'error surface' : 'no heading')
      continue
    }

    const { problems, horizontalScroll, scrollWidth, docWidth } = await audit()
    record(`${name}: no sideways scrolling`, !horizontalScroll, horizontalScroll ? `scrollWidth ${scrollWidth} > ${docWidth}` : '')

    const grouped = {}
    for (const p of problems) (grouped[p.kind] ??= []).push(p)
    for (const kind of Object.keys(grouped)) {
      record(`${name}: no ${kind}`, false, `${grouped[kind].length} found`)
      for (const p of grouped[kind].slice(0, 6)) {
        note(`  ${p.el} — ${p.detail} — "${p.text}"`)
      }
    }
    if (problems.length === 0) record(`${name}: layout clean`, true)
  }
} catch (e) {
  record('phase 5 completed', false, String(e).slice(0, 300))
} finally {
  dumpFaults('layout-' + TAG)
  summary('layout-' + TAG)
  await browser.close()
}

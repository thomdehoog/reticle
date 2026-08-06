/**
 * Invariants of the stylesheet that need no browser to check.
 *
 * Reticle is read standing at an instrument, often on a phone, often in a room
 * kept dark — so the floors below are not style preferences. Text under 12px is
 * not legible at arm's length in that room, and a control under 24px cannot be
 * hit with a thumb (WCAG 2.2 Target Size, Minimum). Both are easy to reintroduce
 * one declaration at a time and impossible to notice from a desk.
 *
 * What is measured here is what the source says, and only where the source is
 * the whole answer. Sizes given in `em` depend on whatever the parent turns out
 * to be, and a target's height usually comes from padding and line-height
 * rather than from any single declaration — those are measured in a real
 * browser by `e2e/smoke.mjs`, which walks the rendered page at 320px and fails
 * on anything under either floor.
 *
 * Nothing here names a class that only one layout would use. A test that
 * asserts how the header is built stops the header being built another way,
 * which is not what it is for.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8')

/** The root font size every `rem` in the sheet resolves against. */
const ROOT_PX = 16

const MINIMUM_TEXT_PX = 12

describe('app.css', () => {
  it('declares no text below the size a dark room can be read at', () => {
    const tooSmall: string[] = []

    for (const [, value, unit] of stylesheet.matchAll(/font-size:\s*([0-9.]+)(rem|px)\s*;/g)) {
      const pixels = unit === 'rem' ? Number(value) * ROOT_PX : Number(value)
      if (pixels < MINIMUM_TEXT_PX) tooSmall.push(`${value}${unit} = ${pixels}px`)
    }

    expect(tooSmall).toEqual([])
  })

  /**
   * The annotation count sat at `bottom: 3px; left: 3px` — the same corner as
   * "move image earlier" — and being painted last it took the click as well as
   * the corner. A picture carrying an annotation could not be moved back down
   * the strip with a mouse at all. The count is not a control, so it must not
   * be able to answer a click wherever it ends up.
   */
  it('keeps the media badge from swallowing a click meant for a button', () => {
    const badge = ruleFor('.media-slot__badge')
    expect(badge).toMatch(/pointer-events:\s*none/)
  })

  it('does not park the media badge in the corner the reorder buttons use', () => {
    /* `.media-slot__earlier` is pinned to the left of the bottom edge and
       `.media-slot__later` sits just inboard of it, so the badge has to be
       measured from the right or it lands on one of them. */
    const badge = ruleFor('.media-slot__badge')
    expect(badge).toMatch(/(^|;)\s*right:/)
    expect(badge).not.toMatch(/(^|;)\s*left:/)
  })

  /**
   * `Thumbnail` renders one element carrying both `.thumb` and `.tile__media`,
   * so `.thumb`'s `height: 100%` lands on the element `.tile__media` is asking
   * to hold at 16/10 — and a definite height beats a ratio. The tile with the
   * shorter title grew its picture to fill the row's spare height, so cards
   * side by side showed their images at different heights and the drawn
   * placeholder had its monogram cropped away. The correction has to come
   * after `.thumb`, because the two selectors weigh the same.
   */
  it('lets a tile keep its picture at the ratio it is composed at', () => {
    const thumbHeight = stylesheet.indexOf('.thumb__image,')
    const correction = stylesheet.lastIndexOf('.tile__media')

    expect(thumbHeight).toBeGreaterThan(-1)
    expect(correction).toBeGreaterThan(thumbHeight)
    expect(stylesheet.slice(correction)).toMatch(/height:\s*auto/)
  })

  /**
   * The same trap one floor down, and it was walked into: `.rail__item` sets
   * `padding` as a shorthand and `.rail__item--step` sets `padding-left` from
   * the row's depth. They weigh the same, so the shorthand wins on order alone
   * and flattens the path into a list of alternatives.
   *
   * Worth a test rather than a comment because nothing else can see it. jsdom
   * computes no layout, so every unit test passed with the indent gone, and the
   * only thing that caught it was looking at a screenshot.
   */
  it('lets the path indent survive the padding it is written against', () => {
    const base = stylesheet.indexOf('.rail__item {')
    const step = stylesheet.indexOf('.rail__item--step {')

    expect(base).toBeGreaterThan(-1)
    expect(step).toBeGreaterThan(base)
  })
})

/** The body of the last rule whose selector list mentions `selector`. */
function ruleFor(selector: string): string {
  const at = stylesheet.lastIndexOf(selector)
  if (at === -1) throw new Error(`No rule for ${selector} in app.css`)
  const open = stylesheet.indexOf('{', at)
  const close = stylesheet.indexOf('}', open)
  return stylesheet.slice(open, close)
}

/**
 * The editors are gated by one media query rather than by a width in the
 * JavaScript. That makes the stylesheet the only place the breakpoint exists —
 * and the only place a test can check it, since jsdom applies no media queries.
 */
describe('the desktop-only gate', () => {
  it('hides the editor and shows the note below the breakpoint', () => {
    const gate = stylesheet.slice(stylesheet.indexOf('.desktop-only {'))
    const media = gate.slice(gate.indexOf('@media (max-width: 900px)'))
    const block = media.slice(0, media.indexOf('\n}\n'))

    expect(block).toMatch(/\.desktop-only\s*\{\s*display:\s*block/)
    expect(block).toMatch(/\.desktop-only__work\s*\{\s*display:\s*none/)
  })

  it('leaves the note hidden by default, so a wide screen never sees it', () => {
    const at = stylesheet.indexOf('.desktop-only {')
    expect(at).toBeGreaterThan(-1)
    expect(stylesheet.slice(at, stylesheet.indexOf('}', at))).toMatch(/display:\s*none/)
  })

  /**
   * The publishing controls are hidden with the editor. Offering Publish and
   * Archive under a note saying to come back at a computer invites somebody to
   * change what a whole institute reads without seeing what they are changing.
   * Source order is the whole mechanism: both selectors weigh the same, so the
   * one inside the media query only wins by being later.
   */
  it('lets the gate win over the action bar it hides', () => {
    const actions = stylesheet.indexOf('.page-actions__editing {')
    const hide = stylesheet.indexOf('.desktop-only__work {')

    expect(actions).toBeGreaterThan(-1)
    expect(hide).toBeGreaterThan(actions)
  })
})

/**
 * The editor's step card and the reader's step are placed by one set of grid
 * rules. Two grids meant to be identical drift the first time only one is
 * adjusted, and the whole argument for the editor's layout is that it is the
 * reader's.
 */
describe('the shared step grid', () => {
  /**
   * Where each of the three lands, not merely that a rule mentions it. The
   * placements are the layout: the picture and its thumbnails share the left
   * column, one above the other, and the points take the whole of the right.
   * Asserting only that the selectors exist would have passed just as happily
   * with the strip back in the text column, which is what it is moving out of.
   */
  it.each([
    ['the stage', '.step__body > .step__stage,\n.editor-step__body > .media-stage', '1', '1'],
    ['the strip', '.step__body > .step__thumbs,\n.editor-step__body > .media-strip', '2', '1'],
    ['the points', '.step__body > .bullets,\n.editor-step__body > .editor-step__points', '1 / -1', '2'],
  ])('places %s from one rule', (_what, selector, column, row) => {
    const at = stylesheet.indexOf(selector)
    expect(at).toBeGreaterThan(-1)

    const body = stylesheet.slice(stylesheet.indexOf('{', at), stylesheet.indexOf('}', at))
    expect(body).toContain(`grid-column: ${column};`)
    expect(body).toContain(`grid-row: ${row};`)
  })

  /**
   * The picture is capped and the lane beside it is fixed, so the row cannot be
   * carved up by whichever child happens to want more.
   *
   * This is the failure the change actually had: the strip kept three equal
   * columns from the days when it ran *under* the picture, and standing it
   * beside one it claimed 736px of the row and left the picture 377px — the
   * reverse of the arrangement the two are meant to share. Each lane is a named
   * width now, and the reader's is narrower than the author's because a
   * thumbnail is a picture and a slot is a picture with a field under it.
   */
  it('gives the picture a ceiling and each strip a lane of its own', () => {
    const grid = stylesheet.slice(stylesheet.indexOf('.step__body,\n.editor-step__body {'))
    expect(grid.slice(0, grid.indexOf('}'))).toContain(
      'grid-template-columns: minmax(0, var(--step-image-max)) auto;',
    )

    /* Searched with a leading newline: the placement rules above end in
       `> .media-strip {`, and a bare search finds those instead of the rule
       that actually sizes the tracks. */
    const reader = stylesheet.slice(stylesheet.indexOf('\n.step__thumbs {'))
    expect(reader.slice(0, reader.indexOf('}'))).toContain(
      'grid-template-columns: var(--step-thumb-width);',
    )

    const editor = stylesheet.slice(stylesheet.indexOf('\n.media-strip {'))
    expect(editor.slice(0, editor.indexOf('}'))).toContain(
      'grid-template-columns: var(--editor-slot-width);',
    )

    const thumb = stylesheet.slice(stylesheet.indexOf('\n.step__thumb {'))
    expect(thumb.slice(0, thumb.indexOf('}'))).not.toContain('max-width')
  })

  /* Beside the picture a single column; under it, on a phone, a row again. */
  it('lays the thumbnails back into a row once they are under the picture', () => {
    const phone = stylesheet.slice(stylesheet.indexOf('@media (max-width: 640px)'))
    const block = phone.slice(0, phone.indexOf('\n}\n'))

    expect(block).toMatch(/\.step__body > \.step__thumbs \{[^}]*repeat\(auto-fill/)
  })

  /**
   * The reader's step still has to stack on a phone. The editor's does not, and
   * must not carry a rule pretending otherwise: it is replaced by a sentence
   * below 900px, so a phone rule for it is a rule that can never run — the kind
   * that survives a rewrite and quietly contradicts the layout above it.
   */
  it('stacks the reader on a phone and says nothing about the editor there', () => {
    const phone = stylesheet.slice(stylesheet.indexOf('@media (max-width: 640px)'))
    const block = phone.slice(0, phone.indexOf('\n}\n'))

    expect(block).toContain('.step__body {')
    expect(block).not.toContain('editor-step')
    expect(block).not.toContain('media-strip')
  })
})

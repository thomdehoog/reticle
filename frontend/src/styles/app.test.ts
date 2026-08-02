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
})

/** The body of the last rule whose selector list mentions `selector`. */
function ruleFor(selector: string): string {
  const at = stylesheet.lastIndexOf(selector)
  if (at === -1) throw new Error(`No rule for ${selector} in app.css`)
  const open = stylesheet.indexOf('{', at)
  const close = stylesheet.indexOf('}', open)
  return stylesheet.slice(open, close)
}

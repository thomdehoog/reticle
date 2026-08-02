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

  it('keeps the section list after the guide rather than in front of it', () => {
    /* Above the content on a narrow screen it is a list of other procedures
       standing between a reader and the one they opened. */
    const rule = stylesheet.match(/\.section-nav \{[^}]*order: 2;[^}]*\}/)
    expect(rule, '.section-nav is not ordered after the content on a narrow screen').not.toBeNull()
  })
})

/**
 * Invariants of the stylesheet that need no browser to check.
 *
 * Reticle is read standing at an instrument, often on a phone, often in a room
 * kept dark — so the floors below are not style preferences. Text under 12px is
 * not legible at arm's length in that room, and a control under 24px cannot be
 * hit with a thumb (WCAG 2.2 Target Size, Minimum). Both are easy to reintroduce
 * one declaration at a time and impossible to notice from a desk.
 *
 * What is measured here is what the source says. Sizes given in `em` depend on
 * whatever the parent turns out to be, and a target's height usually comes from
 * padding and line-height rather than from any single declaration — those are
 * measured in a real browser by `e2e/smoke.mjs`, which walks the rendered page
 * at 320px and fails on anything under either floor.
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
   * The header collapses to one row on a phone and everything else moves into
   * the menu. Without the panel rule the links would still be laid out in the
   * header, wrapping it back to the four rows that cost 233px of a 568px screen
   * before any content at all.
   */
  it('turns the header into one row and a menu on a phone', () => {
    const mobile = stylesheet.match(/@media \(max-width: 860px\) \{([\s\S]*?)\n\}/)
    expect(mobile, 'the phone header breakpoint is missing').not.toBeNull()

    expect(mobile![1]).toContain('.app__menu-toggle')
    expect(mobile![1]).toContain('.app__drawer')
    expect(stylesheet).toContain('display: contents')
  })

  it('keeps the section list after the guide rather than in front of it', () => {
    /* Above the content on a narrow screen it is a list of other procedures
       standing between a reader and the one they opened. */
    const rule = stylesheet.match(/\.section-nav \{[^}]*order: 2;[^}]*\}/)
    expect(rule, '.section-nav is not ordered after the content on a narrow screen').not.toBeNull()
  })
})

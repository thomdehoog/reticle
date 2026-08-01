import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { ANNOTATION_COLORS } from '../components/AnnotationOverlay'
import { BULLET_COLOR_HEX, BULLET_COLOR_ORDER, bulletColorProperty } from './palette'
import type { BulletColor } from './types'

/* Read as text rather than imported: vitest runs with `css: false`, and the
   point here is what the stylesheet actually declares. */
const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8')

function declaredInCss(property: string): string | null {
  const match = stylesheet.match(new RegExp(`${property}:\\s*(#[0-9a-fA-F]{6})`))
  return match ? match[1].toLowerCase() : null
}

describe('the bullet palette', () => {
  it('covers every colour in the model, once', () => {
    expect(BULLET_COLOR_ORDER).toHaveLength(8)
    expect(new Set(BULLET_COLOR_ORDER).size).toBe(8)
    expect(Object.keys(BULLET_COLOR_HEX).sort()).toEqual([...BULLET_COLOR_ORDER].sort())
  })

  /**
   * The one that matters. A bullet says "the red rectangle" and the annotation
   * drawn on the picture has to be that same red — the pairing is the whole
   * reason annotations are stored with a `BulletColor` rather than a free hex
   * value. The stylesheet cannot import the module, so this asserts the two
   * copies agree instead of trusting that they will.
   */
  it('renders bullets and annotations from one set of tokens', () => {
    for (const color of BULLET_COLOR_ORDER) {
      const fromCss = declaredInCss(bulletColorProperty(color))
      expect(fromCss, `--bullet-${color} is missing from app.css`).not.toBeNull()
      expect(fromCss).toBe(BULLET_COLOR_HEX[color].toLowerCase())
      expect(ANNOTATION_COLORS[color]).toBe(BULLET_COLOR_HEX[color])
    }
  })

  it('names each custom property the way the stylesheet spells it', () => {
    expect(bulletColorProperty('light_blue')).toBe('--bullet-light-blue')
    expect(bulletColorProperty('red')).toBe('--bullet-red')
  })

  it('has a class for every colour, so no bullet renders unstyled', () => {
    for (const color of BULLET_COLOR_ORDER) {
      expect(stylesheet).toContain(`.bullet--color-${color}`)
    }
  })

  it('leaves no colour in the model without a palette entry', () => {
    /* Widening BulletColor without touching the palette is the failure this
       catches: TypeScript would accept the new member everywhere and the UI
       would render it as `undefined`. */
    const declared: Record<BulletColor, true> = {
      black: true,
      red: true,
      orange: true,
      yellow: true,
      green: true,
      light_blue: true,
      blue: true,
      violet: true,
    }
    expect(Object.keys(declared).sort()).toEqual(Object.keys(BULLET_COLOR_HEX).sort())
  })
})

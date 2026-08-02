import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { ANNOTATION_COLORS } from '../components/AnnotationOverlay'
import { BULLET_COLOR_HEX, BULLET_COLOR_ORDER, bulletColorProperty } from './palette'
import type { BulletColor } from './types'

/* Read as text rather than imported: vitest runs with `css: false`, and the
   point here is what the stylesheet actually declares. */
const stylesheet = readFileSync(resolve(process.cwd(), 'src/styles/app.css'), 'utf8')

/**
 * The body of every `:root` block, in source order — the light theme, then the
 * dark override, then print.
 *
 * A single regex over the whole file only ever matches the first of them, so a
 * dark theme is free to contradict the palette while the test still passes.
 * Every assertion below therefore names which blocks it is talking about.
 */
function rootBlocks(): string[] {
  return [...stylesheet.matchAll(/:root\s*\{([^}]*)\}/g)].map((match) => match[1])
}

/** What a block declares for a property, or null if it does not mention it. */
function declaredIn(block: string, property: string): string | null {
  const match = block.match(new RegExp(`${property}:\\s*([^;]+);`))
  return match ? match[1].trim().toLowerCase() : null
}

/** `--shape-light-blue` — the fixed colour a shape and its marker are drawn in. */
function shapeProperty(color: BulletColor): string {
  return `--shape-${color.replace(/_/g, '-')}`
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
  it('renders shapes and bullet markers from one set of tokens', () => {
    const blocks = rootBlocks()

    for (const color of BULLET_COLOR_ORDER) {
      const declarations = blocks
        .map((block) => declaredIn(block, shapeProperty(color)))
        .filter((value) => value !== null)

      expect(declarations, `${shapeProperty(color)} is missing from app.css`).toHaveLength(1)
      expect(declarations[0]).toBe(BULLET_COLOR_HEX[color].toLowerCase())
      expect(ANNOTATION_COLORS[color]).toBe(BULLET_COLOR_HEX[color])
    }
  })

  /**
   * Declared exactly once, in the light block, and never overridden. A shape
   * sits on a photograph and the photograph does not change when the page turns
   * dark, so a marker that followed the theme would put a near-white dot beside
   * a near-black shape — precisely in the darkened room the dark theme exists
   * for.
   */
  it('never lets a theme move a shape colour', () => {
    for (const color of BULLET_COLOR_ORDER) {
      const mentions = stylesheet.match(new RegExp(`${shapeProperty(color)}:`, 'g')) ?? []
      expect(mentions, `${shapeProperty(color)} is declared more than once`).toHaveLength(1)
    }
  })

  it('gives every theme that retunes the bullet text all eight colours', () => {
    /* Text is not a photograph: the near-black bullet has to lighten on a dark
       page or it cannot be read. A block that retunes some of them and not the
       rest leaves those bullets rendering in the inherited ink. */
    const themed = rootBlocks().filter((block) => block.includes('--bullet-'))
    expect(themed.length, 'only one theme is being checked').toBeGreaterThan(1)

    for (const block of themed) {
      for (const color of BULLET_COLOR_ORDER) {
        expect(declaredIn(block, bulletColorProperty(color))).not.toBeNull()
      }
    }
  })

  it('names each custom property the way the stylesheet spells it', () => {
    expect(bulletColorProperty('light_blue')).toBe('--bullet-light-blue')
    expect(bulletColorProperty('red')).toBe('--bullet-red')
  })

  it('points every bullet class at its own fixed marker colour', () => {
    for (const color of BULLET_COLOR_ORDER) {
      const rule = stylesheet.match(new RegExp(`\\.bullet--color-${color}\\s*\\{([^}]*)\\}`))
      expect(rule, `.bullet--color-${color} is missing from app.css`).not.toBeNull()
      expect(rule![1]).toContain(`--marker-ink: var(${shapeProperty(color)})`)
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

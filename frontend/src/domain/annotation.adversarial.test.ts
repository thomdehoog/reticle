/**
 * Adversarial probes against the annotation geometry.
 *
 * The interesting question is not "does a normal drag work" but "can a hostile
 * or clumsy drag produce a shape the rest of the system cannot store or show".
 */

import { describe, expect, it } from 'vitest'

import { clampFraction, isMeaningfulDrag, normaliseAnnotation } from './annotation'
import type { Annotation } from './types'

function annotation(overrides: Partial<Annotation> = {}): Annotation {
  return {
    id: 'a1',
    shape: 'rectangle',
    color: 'red',
    x: 0,
    y: 0,
    width: 0,
    height: 0,
    ...overrides,
  }
}

/**
 * What the server will accept, transcribed from `AnnotationIn` in
 * backend/app/schemas.py: coordinates within a small tolerance of the image,
 * a signed extent only for an arrow, and both ends on the picture.
 */
const EDGE_TOLERANCE = 0.05

function serverAccepts(a: Annotation): boolean {
  const inRange = (value: number) =>
    Number.isFinite(value) && value >= -EDGE_TOLERANCE && value <= 1 + EDGE_TOLERANCE
  if (![a.x, a.y, a.x + a.width, a.y + a.height].every(inRange)) return false
  if (a.shape !== 'arrow' && (a.width < 0 || a.height < 0)) return false
  return true
}

const HOSTILE_DRAGS: Partial<Annotation>[] = [
  { x: Number.NaN, y: 0.5, width: 0.2, height: 0.2 },
  { x: 0.5, y: 0.5, width: Number.NaN, height: Number.NaN },
  { x: Number.POSITIVE_INFINITY, y: 0.5, width: 0.2, height: 0.2 },
  { x: -3, y: -3, width: 9, height: 9 },
  { x: 0.9, y: 0.9, width: 4, height: 4 },
  { x: 1.5, y: 1.5, width: -0.2, height: -0.2 },
  { x: -0.4, y: 0.5, width: -0.4, height: 0.2 },
]

describe('normaliseAnnotation — hostile coordinates', () => {
  it.each(HOSTILE_DRAGS)('keeps a rectangle inside the image for %o', (overrides) => {
    const stored = normaliseAnnotation(annotation(overrides))

    expect(serverAccepts(stored)).toBe(true)
    expect(stored.x + stored.width).toBeLessThanOrEqual(1)
    expect(stored.y + stored.height).toBeLessThanOrEqual(1)
  })

  it.each(HOSTILE_DRAGS)('keeps an ellipse inside the image for %o', (overrides) => {
    const stored = normaliseAnnotation(annotation({ ...overrides, shape: 'ellipse' }))
    expect(serverAccepts(stored)).toBe(true)
  })

  it('keeps both ends of an arrow on the image', () => {
    for (const overrides of HOSTILE_DRAGS) {
      const stored = normaliseAnnotation(annotation({ ...overrides, shape: 'arrow' }))
      for (const end of [stored.x, stored.y, stored.x + stored.width, stored.y + stored.height]) {
        expect(end).toBeGreaterThanOrEqual(0)
        expect(end).toBeLessThanOrEqual(1)
      }
    }
  })

  /**
   * Clamping a non-finite far corner on its own sends it to 0 — the *near*
   * edge — so a rectangle whose far corner is not a number came out with a
   * negative width, which its own contract says cannot happen. It collapses
   * onto the start instead, and `isMeaningfulDrag` then discards it.
   */
  it('does not invert a rectangle when a corner is non-finite', () => {
    const stored = normaliseAnnotation(
      annotation({ x: 0.5, y: 0.5, width: Number.POSITIVE_INFINITY, height: 0.1 }),
    )

    expect(stored.width).toBeGreaterThanOrEqual(0)
  })

  it('rounds away floating-point noise', () => {
    const stored = normaliseAnnotation(annotation({ x: 0.1, y: 0.2, width: 0.2, height: 0.1 }))
    expect(stored.x).toBe(0.1)
    expect(String(stored.width)).toBe('0.2')
  })

  /**
   * An arrow keeps its direction, and the wire format carries that sign — the
   * two sides agree on one representation. The natural gesture for pointing at
   * a control on the left of a screenshot is a leftwards drag, and a contract
   * that refused it would make the guide unsaveable from then on.
   */
  it('stores an arrow in a form the server will accept', () => {
    const leftwards = annotation({ shape: 'arrow', x: 0.8, y: 0.8, width: -0.5, height: -0.5 })
    const stored = normaliseAnnotation(leftwards)

    expect(stored.width).toBeLessThan(0)
    expect(serverAccepts(stored)).toBe(true)
  })

  it('stores a box the server will accept however it was dragged', () => {
    const upAndLeft = annotation({ shape: 'rectangle', x: 0.8, y: 0.8, width: -0.5, height: -0.5 })
    const stored = normaliseAnnotation(upAndLeft)

    expect(stored.width).toBeGreaterThan(0)
    expect(serverAccepts(stored)).toBe(true)
  })

  /**
   * The editor asks this question after normalising, not before. A drag that
   * happened entirely outside the picture is big enough to keep while it is
   * still raw and collapses to nothing once clamped, and what got stored was an
   * invisible zero-size shape that counted towards the badge and could not be
   * clicked — so it could not be deleted from the drawing surface either.
   */
  it('collapses a drag that happened off the image, so the editor discards it', () => {
    const offImage = annotation({ x: -0.5, y: -0.5, width: 0.2, height: 0.2 })

    const stored = normaliseAnnotation(offImage)
    expect(isMeaningfulDrag(stored)).toBe(false)
  })
})

describe('clampFraction', () => {
  it('treats an infinite coordinate as zero rather than as the far edge', () => {
    // Documented behaviour, not a defect: no pointer can report an infinite
    // position, and 0 is at least inside the image.
    expect(clampFraction(Number.POSITIVE_INFINITY)).toBe(0)
    expect(clampFraction(Number.NEGATIVE_INFINITY)).toBe(0)
  })

  it('refuses -0, which would serialise as "-0" in JSON', () => {
    expect(Object.is(clampFraction(-0), -0)).toBe(false)
  })
})

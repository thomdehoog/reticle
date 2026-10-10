/**
 * Adversarial probes against the annotation geometry.
 *
 * The interesting question is not "does a normal drag work" but "can a hostile
 * or clumsy drag produce a shape the rest of the system cannot store or show".
 */

import { describe, expect, it } from 'vitest'

import { clampFraction, commitDrag, isMeaningfulDrag, normaliseAnnotation } from './annotation'
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
 * What the server will accept, from docs/API.md: `x` and `y` are fractions in
 * 0..1, `width` and `height` in -1..1 — signed, because an arrow may point up
 * or left. Anything outside this is refused on save.
 */
function serverAccepts(a: Annotation): boolean {
  const within = (value: number, low: number) => Number.isFinite(value) && value >= low && value <= 1
  return within(a.x, 0) && within(a.y, 0) && within(a.width, -1) && within(a.height, -1)
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
    expect(stored.width).toBeGreaterThanOrEqual(0)
    expect(stored.height).toBeGreaterThanOrEqual(0)
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
   * `clampFraction` sends a non-finite value to 0, the *near* edge. Comparing
   * the corners before clamping them would then put a rectangle's far edge
   * behind its near one and store a negative width, which the function's own
   * contract says cannot happen. No pointer reports an infinite coordinate, so
   * this is a guard rather than a reachable path — but it is the guard.
   */
  it('does not invert a rectangle when a corner is non-finite', () => {
    const stored = normaliseAnnotation(
      annotation({ x: 0.5, y: 0.5, width: Number.POSITIVE_INFINITY, height: 0.1 }),
    )

    expect(stored.width).toBeGreaterThanOrEqual(0)
    expect(serverAccepts(stored)).toBe(true)
  })

  it('rounds away floating-point noise', () => {
    const stored = normaliseAnnotation(annotation({ x: 0.1, y: 0.2, width: 0.2, height: 0.1 }))
    expect(stored.x).toBe(0.1)
    expect(String(stored.width)).toBe('0.2')
  })

  /**
   * An arrow is stored with signed extents so it keeps its direction: which end
   * carries the head is the whole point of it. Pointing left or up — the
   * natural gesture for a control on the left of a screenshot — therefore
   * stores a negative width or height, and the contract allows exactly that.
   */
  it('stores an arrow in a form the server will accept', () => {
    const leftwards = annotation({ shape: 'arrow', x: 0.8, y: 0.8, width: -0.5, height: -0.5 })
    const stored = normaliseAnnotation(leftwards)

    expect(stored.width).toBeLessThan(0)
    expect(serverAccepts(stored)).toBe(true)
  })

  it.each(HOSTILE_DRAGS)('keeps an arrow storable for %o', (overrides) => {
    expect(serverAccepts(normaliseAnnotation(annotation({ ...overrides, shape: 'arrow' })))).toBe(
      true,
    )
  })

  /**
   * A drag that happens entirely outside the image (possible once the pointer
   * is captured) is long enough to look deliberate, and then collapses to
   * nothing when clamped. Committed, that would be an invisible zero-size
   * shape: stored, counted in the slot badge, and impossible to click to delete.
   */
  it('never commits a shape that clamping has collapsed to nothing', () => {
    const offImage = annotation({ x: -0.5, y: -0.5, width: 0.2, height: 0.2 })

    expect(isMeaningfulDrag(offImage)).toBe(true)
    expect(commitDrag(offImage)).toBeNull()
  })

  it('commits an ordinary drag as its stored form', () => {
    const drag = annotation({ x: 0.6, y: 0.6, width: -0.3, height: -0.2 })
    expect(commitDrag(drag)).toEqual(normaliseAnnotation(drag))
    expect(commitDrag(annotation({ x: 0.5, y: 0.5, width: 0.001, height: 0.001 }))).toBeNull()
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

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
 * backend/app/schemas.py:293-305 — every one of x, y, width and height is
 * `float = Field(ge=0.0, le=1.0)`. Anything outside this is a 422 on save.
 */
function serverAccepts(a: Annotation): boolean {
  return [a.x, a.y, a.width, a.height].every(
    (value) => Number.isFinite(value) && value >= 0 && value <= 1,
  )
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
   * DEFECT (low, defensive only): `clampFraction` sends every non-finite value
   * to 0 — src/domain/annotation.ts:17-20 — so it lands on the *near* edge even
   * when it is being used to clamp the far corner. For a rectangle whose far
   * corner is non-finite, `right` becomes 0 while `left` stays where the drag
   * began, and the stored width comes out negative: a rectangle with a negative
   * extent, which the function's own contract says cannot happen and which the
   * server rejects (`ge=0.0`).
   *
   * No pointer can report an infinite coordinate, so this is not reachable from
   * the drawing surface today; it is the guard that is meant to make hostile
   * input harmless failing to do so.
   */
  it.fails('does not invert a rectangle when a corner is non-finite', () => {
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
   * DEFECT (high): an arrow is stored with signed extents so it keeps its
   * direction — src/domain/annotation.ts:40-51, and the shipped test at
   * src/domain/annotation.test.ts asserts `stored.width` is negative for an
   * arrow dragged up and to the left. The server refuses exactly that:
   * `AnnotationIn.width`/`height` are `Field(ge=0.0, le=1.0)` in
   * backend/app/schemas.py:302-304.
   *
   * So an author who draws an arrow pointing left or up — the natural gesture
   * for pointing at a control on the left of a screenshot — makes the whole
   * guide unsaveable: every autosave from then on is rejected with
   * `validation_failed`, and the editor shows only "Could not save".
   *
   * The two sides have to agree on one representation. Either the wire format
   * carries a signed vector (or explicit start/end points), or the client stores
   * the head separately from the box.
   */
  it.fails('stores an arrow in a form the server will accept', () => {
    const leftwards = annotation({ shape: 'arrow', x: 0.8, y: 0.8, width: -0.5, height: -0.5 })
    const stored = normaliseAnnotation(leftwards)

    // Direction is preserved, which is the intent...
    expect(stored.width).toBeLessThan(0)
    // ...but the server will not take it.
    expect(serverAccepts(stored)).toBe(true)
  })

  /**
   * DEFECT (low): `isMeaningfulDrag` is asked about the raw drag, before
   * normalisation clamps it — src/components/editor/AnnotationEditor.tsx:101-102.
   * A drag that happens entirely outside the image (possible once the pointer is
   * captured, and off-by-a-scroll coordinates make it likelier still) passes the
   * "big enough to keep" test and then collapses to nothing when clamped.
   *
   * The result is an invisible zero-size shape that is stored, counted in the
   * slot badge, and cannot be clicked to select — so it cannot be deleted from
   * the drawing surface either.
   */
  it.fails('never commits a shape that clamping has collapsed to nothing', () => {
    const offImage = annotation({ x: -0.5, y: -0.5, width: 0.2, height: 0.2 })

    expect(isMeaningfulDrag(offImage)).toBe(true) // the editor decides to keep it
    const stored = normaliseAnnotation(offImage)
    expect(isMeaningfulDrag(stored)).toBe(true) // but there is nothing left
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

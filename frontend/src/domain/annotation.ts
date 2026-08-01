/**
 * Pure geometry for image annotations.
 *
 * Kept out of the component for the same reason the step logic is: the rules
 * about what a dragged shape becomes are worth testing directly rather than
 * through a simulated pointer gesture.
 *
 * Every coordinate is a fraction of the image in 0..1. Storing pixels would
 * pin an annotation to whatever screen it was drawn on.
 */

import type { Annotation } from './types'

/** Below this, a drag was almost certainly a mis-click rather than a shape. */
export const MINIMUM_DRAG_FRACTION = 0.01

export function clampFraction(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(Math.max(value, 0), 1)
}

/**
 * Fractions are stored to five decimals — about a twentieth of a pixel on a
 * 4000-pixel image, which is far finer than anyone can draw. Rounding keeps
 * binary floating-point noise like 0.30000000000000004 out of the database and
 * out of every JSON payload that carries a guide.
 */
function round(value: number): number {
  return Math.round(value * 1e5) / 1e5
}

/**
 * Rewrites a dragged shape into stored form.
 *
 * Rectangles and ellipses are stored with positive extents, so dragging up and
 * to the left produces the same shape as dragging down and to the right. An
 * arrow keeps its direction, because which end carries the head is the whole
 * point of it.
 */
/**
 * Where a drag ended, held inside the image.
 *
 * A far corner that is not a finite number collapses onto the start rather than
 * being clamped on its own. Clamping it alone sends it to 0 — the *near* edge —
 * which for a corner that was meant to be to the right of the start produces a
 * shape with a negative extent: a rectangle that the contract says cannot exist.
 * Collapsing to a zero-size shape instead leaves something `isMeaningfulDrag`
 * then discards, which is the outcome the guard was there to produce.
 */
function clampEnd(start: number, delta: number): number {
  const end = start + delta
  return Number.isFinite(end) ? clampFraction(end) : clampFraction(start)
}

export function normaliseAnnotation(annotation: Annotation): Annotation {
  const startX = clampFraction(annotation.x)
  const startY = clampFraction(annotation.y)
  const endX = clampEnd(annotation.x, annotation.width)
  const endY = clampEnd(annotation.y, annotation.height)

  if (annotation.shape === 'arrow') {
    return {
      ...annotation,
      x: round(startX),
      y: round(startY),
      width: round(endX - startX),
      height: round(endY - startY),
    }
  }

  const left = Math.min(startX, endX)
  const top = Math.min(startY, endY)

  return {
    ...annotation,
    x: round(left),
    y: round(top),
    width: round(Math.max(startX, endX) - left),
    height: round(Math.max(startY, endY) - top),
  }
}

/** True when a drag covered enough ground to be worth keeping. */
export function isMeaningfulDrag(annotation: Annotation): boolean {
  return (
    Math.abs(annotation.width) > MINIMUM_DRAG_FRACTION ||
    Math.abs(annotation.height) > MINIMUM_DRAG_FRACTION
  )
}

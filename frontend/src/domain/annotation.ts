/**
 * Pure geometry for image annotations.
 *
 * Kept out of the component for the same reason the step logic is: the rules
 * about what a dragged shape becomes are worth testing directly rather than
 * through a simulated pointer gesture.
 *
 * Every coordinate is a fraction of the image: a position in 0..1, an extent in
 * -1..1 (only an arrow's is ever negative). Storing pixels would pin an
 * annotation to whatever screen it was drawn on.
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
export function normaliseAnnotation(annotation: Annotation): Annotation {
  if (annotation.shape === 'arrow') {
    const startX = clampFraction(annotation.x)
    const startY = clampFraction(annotation.y)
    return {
      ...annotation,
      x: round(startX),
      y: round(startY),
      width: round(clampFraction(annotation.x + annotation.width) - startX),
      height: round(clampFraction(annotation.y + annotation.height) - startY),
    }
  }

  /* Each corner is brought onto the image before the two are compared, so a
     corner that is off it — or is not a number at all — cannot leave the far
     edge on the wrong side of the near one. */
  const nearX = clampFraction(annotation.x)
  const farX = clampFraction(annotation.x + annotation.width)
  const nearY = clampFraction(annotation.y)
  const farY = clampFraction(annotation.y + annotation.height)

  const left = Math.min(nearX, farX)
  const top = Math.min(nearY, farY)
  const right = Math.max(nearX, farX)
  const bottom = Math.max(nearY, farY)

  return {
    ...annotation,
    x: round(left),
    y: round(top),
    width: round(right - left),
    height: round(bottom - top),
  }
}

/** True when a drag covered enough ground to be worth keeping. */
export function isMeaningfulDrag(annotation: Annotation): boolean {
  return (
    Math.abs(annotation.width) > MINIMUM_DRAG_FRACTION ||
    Math.abs(annotation.height) > MINIMUM_DRAG_FRACTION
  )
}

/**
 * What a finished drag becomes: the stored shape, or null when there is nothing
 * worth keeping.
 *
 * The size test is applied to the *stored* shape, not the raw drag. A drag made
 * entirely off the image is long enough to pass as deliberate, then clamps to a
 * shape of no size at all — one that would be saved, counted on the image's
 * badge, and impossible to click on to delete.
 */
export function commitDrag(annotation: Annotation): Annotation | null {
  const stored = normaliseAnnotation(annotation)
  return isMeaningfulDrag(stored) ? stored : null
}

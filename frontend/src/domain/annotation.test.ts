import { describe, expect, it } from 'vitest'

import { clampFraction, isMeaningfulDrag, normaliseAnnotation } from './annotation'
import type { Annotation } from './types'

function annotation(overrides: Partial<Annotation> = {}): Annotation {
  return {
    id: 'a1',
    shape: 'rectangle',
    color: 'red',
    x: 0.1,
    y: 0.2,
    width: 0.3,
    height: 0.4,
    ...overrides,
  }
}

describe('clampFraction', () => {
  it.each([
    [-0.5, 0],
    [0, 0],
    [0.42, 0.42],
    [1, 1],
    [1.7, 1],
    [Number.NaN, 0],
  ])('clamps %s to %s', (input, expected) => {
    expect(clampFraction(input)).toBe(expected)
  })
})

describe('normaliseAnnotation', () => {
  it('leaves a rectangle dragged down-and-right alone', () => {
    expect(normaliseAnnotation(annotation())).toEqual(annotation())
  })

  it('rewrites a rectangle dragged up-and-left to positive extents', () => {
    const dragged = annotation({ x: 0.8, y: 0.9, width: -0.3, height: -0.4 })
    const stored = normaliseAnnotation(dragged)

    expect(stored.x).toBeCloseTo(0.5)
    expect(stored.y).toBeCloseTo(0.5)
    expect(stored.width).toBeCloseTo(0.3)
    expect(stored.height).toBeCloseTo(0.4)
  })

  it('keeps a shape inside the image when the drag left it', () => {
    const dragged = annotation({ x: 0.9, y: 0.9, width: 0.5, height: 0.5 })
    const stored = normaliseAnnotation(dragged)

    expect(stored.x + stored.width).toBeLessThanOrEqual(1)
    expect(stored.y + stored.height).toBeLessThanOrEqual(1)
  })

  it('preserves an arrow’s direction, because the head end is the meaning', () => {
    const upLeft = annotation({ shape: 'arrow', x: 0.8, y: 0.8, width: -0.5, height: -0.5 })
    const stored = normaliseAnnotation(upLeft)

    expect(stored.x).toBeCloseTo(0.8)
    expect(stored.y).toBeCloseTo(0.8)
    expect(stored.width).toBeLessThan(0)
    expect(stored.height).toBeLessThan(0)
  })

  it('clamps an arrow that was dragged off the edge without flipping it', () => {
    const offEdge = annotation({ shape: 'arrow', x: 0.5, y: 0.5, width: -0.9, height: 0.9 })
    const stored = normaliseAnnotation(offEdge)

    expect(stored.x + stored.width).toBeCloseTo(0)
    expect(stored.y + stored.height).toBeCloseTo(1)
  })
})

describe('isMeaningfulDrag', () => {
  it('rejects a click that barely moved', () => {
    expect(isMeaningfulDrag(annotation({ width: 0.002, height: 0.002 }))).toBe(false)
  })

  it('accepts a drag that moved in only one direction', () => {
    expect(isMeaningfulDrag(annotation({ width: 0.4, height: 0 }))).toBe(true)
    expect(isMeaningfulDrag(annotation({ width: 0, height: 0.4 }))).toBe(true)
  })

  it('accepts a drag up and to the left', () => {
    expect(isMeaningfulDrag(annotation({ width: -0.4, height: -0.4 }))).toBe(true)
  })
})

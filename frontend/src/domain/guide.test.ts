import { describe, expect, it } from 'vitest'

import {
  canAcceptMedia,
  createStep,
  formatDurationRange,
  indentBullet,
  insertStepAfter,
  moveStep,
  newId,
  removeStep,
  renumberSteps,
  validateForPublish,
} from './guide'
import type { Guide, Media, Step } from './types'

function stepWithTitle(title: string, orderIndex: number): Step {
  return createStep({ title, orderIndex })
}

function threeSteps(): Step[] {
  return [stepWithTitle('Mount', 0), stepWithTitle('Focus', 1), stepWithTitle('Acquire', 2)]
}

function media(id: string): Media {
  return { id, url: `/api/media/${id}`, alt: '', width: 800, height: 600, annotations: [] }
}

function guideFixture(overrides: Partial<Guide> = {}): Guide {
  const user = { id: 'u1', displayName: 'Thom de Hoog' }
  return {
    id: 'g1',
    slug: 'confocal-startup',
    title: 'Confocal startup',
    summary: '',
    categoryId: 'c-light-microscopy',
    tags: [],
    difficulty: 'moderate',
    timeRequiredMinMinutes: 30,
    timeRequiredMaxMinutes: null,
    introduction: '',
    conclusion: '',
    status: 'draft',
    steps: threeSteps().map((step) => ({
      ...step,
      bullets: [{ id: `b-${step.title}`, text: 'Do the thing', color: 'black', icon: null, level: 0 }],
    })),
    author: user,
    lastEditedBy: user,
    contributors: [user],
    viewCount: 0,
    createdAt: '2026-07-31T08:00:00Z',
    updatedAt: '2026-07-31T08:00:00Z',
    publishedAt: null,
    version: 0,
    ...overrides,
  }
}

describe('newId', () => {
  it('mints unique ULIDs the server will accept', () => {
    const ids = new Set(Array.from({ length: 200 }, () => newId()))
    expect(ids.size).toBe(200)
    /* The server validates every client-supplied id and refuses anything that
       is not a ULID, so a placeholder scheme would break autosave the moment
       an author added a step. */
    for (const id of ids) expect(id).toMatch(/^[0-9A-HJKMNP-TV-Z]{26}$/)
  })
})

describe('renumberSteps', () => {
  it('rewrites orderIndex to match array position', () => {
    const scrambled = [stepWithTitle('a', 7), stepWithTitle('b', 2), stepWithTitle('c', 99)]
    expect(renumberSteps(scrambled).map((s) => s.orderIndex)).toEqual([0, 1, 2])
  })

  it('preserves object identity for steps already numbered correctly', () => {
    const steps = threeSteps()
    const result = renumberSteps(steps)
    expect(result[0]).toBe(steps[0])
    expect(result[2]).toBe(steps[2])
  })
})

describe('moveStep', () => {
  it('moves a step later and renumbers', () => {
    const result = moveStep(threeSteps(), 0, 2)
    expect(result.map((s) => s.title)).toEqual(['Focus', 'Acquire', 'Mount'])
    expect(result.map((s) => s.orderIndex)).toEqual([0, 1, 2])
  })

  it('moves a step earlier', () => {
    const result = moveStep(threeSteps(), 2, 0)
    expect(result.map((s) => s.title)).toEqual(['Acquire', 'Mount', 'Focus'])
  })

  it('leaves the array untouched for a no-op or out-of-range move', () => {
    const steps = threeSteps()
    expect(moveStep(steps, 1, 1)).toBe(steps)
    expect(moveStep(steps, -1, 0)).toBe(steps)
    expect(moveStep(steps, 0, 5)).toBe(steps)
  })
})

describe('insertStepAfter', () => {
  it('inserts directly after the given index', () => {
    const result = insertStepAfter(threeSteps(), 0)
    expect(result).toHaveLength(4)
    expect(result[1].title).toBe('')
    expect(result.map((s) => s.orderIndex)).toEqual([0, 1, 2, 3])
    expect(result[2].title).toBe('Focus')
  })

  it('gives a new step one empty bullet to type into', () => {
    const result = insertStepAfter(threeSteps(), 2)
    expect(result[3].bullets).toHaveLength(1)
    expect(result[3].bullets[0].text).toBe('')
    expect(result[3].bullets[0].color).toBe('black')
  })
})

describe('removeStep', () => {
  it('removes and renumbers', () => {
    const result = removeStep(threeSteps(), 1)
    expect(result.map((s) => s.title)).toEqual(['Mount', 'Acquire'])
    expect(result.map((s) => s.orderIndex)).toEqual([0, 1])
  })

  it('refuses to remove the last remaining step', () => {
    const single = [stepWithTitle('only', 0)]
    expect(removeStep(single, 0)).toBe(single)
  })
})

describe('canAcceptMedia', () => {
  it('allows up to three images and no more', () => {
    expect(canAcceptMedia(createStep({ media: [] }))).toBe(true)
    expect(canAcceptMedia(createStep({ media: [media('a'), media('b')] }))).toBe(true)
    expect(canAcceptMedia(createStep({ media: [media('a'), media('b'), media('c')] }))).toBe(false)
  })
})

describe('indentBullet', () => {
  it('clamps between level 0 and level 2', () => {
    const bullet = { id: 'b', text: '', color: 'black' as const, icon: null, level: 0 as const }
    expect(indentBullet(bullet, 1).level).toBe(1)
    expect(indentBullet(bullet, -1)).toBe(bullet)
    expect(indentBullet(indentBullet(indentBullet(bullet, 1), 1), 1).level).toBe(2)
  })
})

describe('formatDurationRange', () => {
  it.each([
    [null, null, 'Not specified'],
    [0, 0, 'Not specified'],
    [5, null, '5 min'],
    [59, null, '59 min'],
    [60, null, '1 h'],
    [90, null, '1 h 30 min'],
    [125, null, '2 h 5 min'],
    [30, 30, '30 min'],
    [30, 90, '30 min – 1 h 30 min'],
    [60, 240, '1 h – 4 h'],
    [null, 45, 'up to 45 min'],
  ])('formats %s..%s as %s', (low, high, expected) => {
    expect(formatDurationRange(low, high)).toBe(expected)
  })

  it('reads a reversed range in the order a person would say it', () => {
    expect(formatDurationRange(90, 30)).toBe('30 min – 1 h 30 min')
  })
})

describe('validateForPublish', () => {
  it('passes a complete guide', () => {
    expect(validateForPublish(guideFixture())).toEqual([])
  })

  it('requires a title', () => {
    const issues = validateForPublish(guideFixture({ title: '   ' }))
    expect(issues.map((i) => i.field)).toContain('title')
  })

  it('requires a category', () => {
    const issues = validateForPublish(guideFixture({ categoryId: '' }))
    expect(issues.map((i) => i.field)).toContain('categoryId')
  })

  it('requires at least one step', () => {
    const issues = validateForPublish(guideFixture({ steps: [] }))
    expect(issues).toEqual([
      { field: 'steps', message: 'A guide needs at least one step.' },
    ])
  })

  it('reports an empty step by its human-facing number', () => {
    const steps = guideFixture().steps
    steps[1] = { ...steps[1], bullets: [{ ...steps[1].bullets[0], text: '  ' }], media: [] }
    const issues = validateForPublish(guideFixture({ steps }))
    expect(issues).toHaveLength(1)
    expect(issues[0].field).toBe('steps.1')
    expect(issues[0].message).toBe(
      'Step 2 is empty — add an instruction or an image, or remove it.',
    )
  })

  it('accepts a step that has an image but no text', () => {
    const steps = guideFixture().steps
    steps[0] = { ...steps[0], bullets: [{ ...steps[0].bullets[0], text: '' }], media: [media('m1')] }
    expect(validateForPublish(guideFixture({ steps }))).toEqual([])
  })

  it('rejects a step carrying more than three images', () => {
    const steps = guideFixture().steps
    steps[0] = { ...steps[0], media: [media('a'), media('b'), media('c'), media('d')] }
    const issues = validateForPublish(guideFixture({ steps }))
    expect(issues).toHaveLength(1)
    expect(issues[0].message).toBe('Step 1 has 4 images; the maximum is 3.')
  })
})

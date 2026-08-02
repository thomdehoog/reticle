import { describe, expect, it } from 'vitest'

import {
  canAcceptMedia,
  createStep,
  formatDurationRange,
  indentBullet,
  insertStepAfter,
  moveMedia,
  moveStep,
  newId,
  numberShapeColors,
  numberedSteps,
  removeStep,
  renumberSteps,
  validateForPublish,
} from './guide'
import type { Annotation, BulletColor, Guide, Media, Step } from './types'

function stepWithTitle(title: string, orderIndex: number): Step {
  return createStep({ title, orderIndex })
}

function threeSteps(): Step[] {
  return [stepWithTitle('Mount', 0), stepWithTitle('Focus', 1), stepWithTitle('Acquire', 2)]
}

function media(id: string): Media {
  return {
    id,
    url: `/api/media/${id}`,
    kind: 'image',
    alt: '',
    width: 800,
    height: 600,
    durationSeconds: null,
    posterUrl: null,
    annotations: [],
  }
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
    isQuickLink: false,
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
  it('allows up to four images and no more', () => {
    expect(canAcceptMedia(createStep({ media: [] }))).toBe(true)
    expect(canAcceptMedia(createStep({ media: [media('a'), media('b'), media('c')] }))).toBe(true)
    expect(
      canAcceptMedia(createStep({ media: [media('a'), media('b'), media('c'), media('d')] })),
    ).toBe(false)
  })

  /* A clip does not compete for an image slot: the step holds one video and its
     stills, and counting them together would cost a step its fourth picture. */
  it('ignores a step video when counting image slots', () => {
    const step = createStep({ media: [media('a')], video: media('v') })
    expect(canAcceptMedia(step)).toBe(true)
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

  it('rejects a step carrying more than four images', () => {
    const steps = guideFixture().steps
    steps[0] = { ...steps[0], media: [media('a'), media('b'), media('c'), media('d'), media('e')] }
    const issues = validateForPublish(guideFixture({ steps }))
    expect(issues).toHaveLength(1)
    expect(issues[0].message).toBe('Step 1 has 5 images; the maximum is 4.')
  })

  it('accepts a step that is only a video, with no text and no stills', () => {
    const steps = guideFixture().steps
    steps[0] = {
      ...steps[0],
      bullets: [{ ...steps[0].bullets[0], text: '' }],
      media: [],
      video: media('v1'),
    }
    expect(validateForPublish(guideFixture({ steps }))).toEqual([])
  })
})

function shape(id: string, color: BulletColor): Annotation {
  return { id, shape: 'rectangle', color, x: 0.1, y: 0.1, width: 0.2, height: 0.2 }
}

function imageWith(id: string, annotations: Annotation[]): Media {
  return { ...media(id), annotations }
}

describe('numberShapeColors', () => {
  it('numbers the shape colours in the order a reader meets them', () => {
    const step = createStep({
      media: [
        imageWith('m1', [shape('a', 'red'), shape('b', 'green')]),
        imageWith('m2', [shape('c', 'blue')]),
      ],
    })

    expect(numberShapeColors(step)).toEqual({ red: 1, green: 2, blue: 3 })
  })

  it('gives one number to every shape of the same colour', () => {
    /* Two red rectangles are both what the red bullet is pointing at, so a
       second number would invent a second instruction. */
    const step = createStep({
      media: [imageWith('m1', [shape('a', 'red'), shape('b', 'red'), shape('c', 'yellow')])],
    })

    expect(numberShapeColors(step)).toEqual({ red: 1, yellow: 2 })
  })

  it('numbers nothing for a step whose pictures carry no shapes', () => {
    expect(numberShapeColors(createStep({ media: [media('m1')] }))).toEqual({})
  })
})

describe('numbering blocks', () => {
  it('counts only real steps, so a callout does not eat a number', () => {
    const numbers = numberedSteps([
      createStep({ id: 'a' }),
      createStep({ id: 'b' }),
      createStep({ id: 'note', kind: 'info' }),
      createStep({ id: 'c' }),
    ])

    expect(numbers.get('a')).toBe(1)
    expect(numbers.get('b')).toBe(2)
    expect(numbers.get('c')).toBe(3)
  })

  it('leaves the blocks that are not numbered out of the map entirely', () => {
    /* Absent rather than zero: a caller that forgets to handle them shows
       nothing, which is right, instead of showing a step 0. */
    const numbers = numberedSteps([
      createStep({ id: 'pin', kind: 'pinned' }),
      createStep({ id: 'first' }),
    ])

    expect(numbers.has('pin')).toBe(false)
    expect(numbers.get('first')).toBe(1)
  })

  it('numbers nothing when a guide is all context', () => {
    expect(numberedSteps([createStep({ id: 'x', kind: 'info' })]).size).toBe(0)
  })
})

describe('choosing which picture leads', () => {
  const pic = (id: string): Media => ({
    id,
    url: `/api/media/${id}`,
    kind: 'image',
    alt: '',
    width: null,
    height: null,
    durationSeconds: null,
    posterUrl: null,
    annotations: [],
  })

  it('moves a picture one place later', () => {
    const moved = moveMedia([pic('a'), pic('b'), pic('c')], 'a', 1)
    expect(moved.map((image) => image.id)).toEqual(['b', 'a', 'c'])
  })

  it('moves a picture one place earlier, which is how an author picks the large one', () => {
    const moved = moveMedia([pic('a'), pic('b')], 'b', -1)
    expect(moved.map((image) => image.id)).toEqual(['b', 'a'])
  })

  it('refuses to wrap around either end', () => {
    /* Wrapping would turn a nudge on the last picture into "make this the one
       everybody sees", which is the opposite of what the click meant. */
    const media = [pic('a'), pic('b')]
    expect(moveMedia(media, 'a', -1)).toBe(media)
    expect(moveMedia(media, 'b', 1)).toBe(media)
  })

  it('leaves the list alone when the picture is not in it', () => {
    const media = [pic('a')]
    expect(moveMedia(media, 'gone', 1)).toBe(media)
  })
})

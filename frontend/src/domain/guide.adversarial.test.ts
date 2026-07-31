/**
 * Adversarial probes against the pure guide logic.
 *
 * Two kinds of attack: nonsense arguments that should not corrupt a document,
 * and agreements with the server that the frontend can quietly break.
 */

import { describe, expect, it } from 'vitest'

import {
  createBullet,
  createStep,
  formatDurationRange,
  formatMinutes,
  indentBullet,
  insertStepAfter,
  moveStep,
  newId,
  removeStep,
  renumberSteps,
  validateForPublish,
} from './guide'
import type { Guide, Step } from './types'

/** Crockford base32, 26 characters — what `ULID.from_str` will parse. */
const ULID_PATTERN = /^[0-9A-HJKMNP-TV-Z]{26}$/

function step(overrides: Partial<Step> = {}): Step {
  return { id: 's1', orderIndex: 0, title: '', bullets: [], media: [], ...overrides }
}

function guide(overrides: Partial<Guide> = {}): Guide {
  const author = { id: 'u1', displayName: 'Thom de Hoog' }
  return {
    id: 'g1',
    slug: 'g',
    title: 'Confocal startup',
    summary: '',
    categoryId: 'c1',
    tags: [],
    difficulty: 'moderate',
    timeRequiredMinMinutes: null,
    timeRequiredMaxMinutes: null,
    introduction: '',
    conclusion: '',
    status: 'draft',
    steps: [step({ bullets: [createBullet({ text: 'Turn the key.' })] })],
    author,
    lastEditedBy: author,
    contributors: [author],
    viewCount: 0,
    createdAt: '2026-07-01T08:00:00Z',
    updatedAt: '2026-07-01T08:00:00Z',
    publishedAt: null,
    version: 0,
    ...overrides,
  }
}

describe('newId — the identifier contract with the server', () => {
  /**
   * This was a real defect, found here and now fixed.
   *
   * The editor used to mint ids of the form `new-<uuid>`, which the server
   * refuses: `_claim_id` in backend/app/documents.py calls `is_valid_id` on
   * every non-null id and raises `validation_failed("step identifiers must be
   * ULIDs.")`. Pressing Enter to start a bullet — the primary authoring gesture
   * — therefore made a guide permanently unsaveable: every autosave from that
   * keystroke on was rejected, the header stuck on "Could not save", and the
   * author kept typing into a document that was no longer reaching the server.
   *
   * The fix mints real ULIDs client-side, which the server explicitly supports:
   * "an unknown one is accepted so an optimistically created row keeps its
   * key". The assertion stays as a regression guard.
   */
  it('mints identifiers the server will accept', () => {
    expect(newId()).toMatch(ULID_PATTERN)
    expect(createStep().id).toMatch(ULID_PATTERN)
    expect(createBullet().id).toMatch(ULID_PATTERN)
  })

  it('at least keeps ids unique within an open document', () => {
    const ids = new Set(Array.from({ length: 500 }, () => newId()))
    expect(ids.size).toBe(500)
  })
})

describe('step algebra under nonsense arguments', () => {
  const three = renumberSteps([step({ id: 'a' }), step({ id: 'b' }), step({ id: 'c' })])

  it.each([
    [-1, 0],
    [0, -1],
    [0, 9],
    [9, 0],
  ])('refuses to move %s to %s', (from, to) => {
    expect(moveStep(three, from, to)).toBe(three)
  })

  it('does not scramble the document when handed a NaN index', () => {
    // NaN passes every `<`/`>=` guard in moveStep, but `splice(NaN, …)` treats
    // it as 0, so the order survives. Worth pinning: the guards are not what is
    // protecting the document here.
    expect(moveStep(three, Number.NaN, 0).map((s) => s.id)).toEqual(['a', 'b', 'c'])
  })

  it.each([-1, 3, Number.NaN])('refuses to remove index %s', (index) => {
    expect(removeStep(three, index)).toEqual(three)
  })

  it('refuses to remove the last remaining step', () => {
    const one = [step({ id: 'only' })]
    expect(removeStep(one, 0)).toBe(one)
  })

  it('clamps an out-of-range insertion point instead of leaving a hole', () => {
    expect(insertStepAfter(three, -99)).toHaveLength(4)
    expect(insertStepAfter(three, 99)).toHaveLength(4)
    for (const inserted of [insertStepAfter(three, -99), insertStepAfter(three, 99)]) {
      expect(inserted.map((s) => s.orderIndex)).toEqual([0, 1, 2, 3])
    }
  })

  it('renumbers a document whose orderIndex disagrees with its array', () => {
    const scrambled = [step({ id: 'a', orderIndex: 7 }), step({ id: 'b', orderIndex: 7 })]
    expect(renumberSteps(scrambled).map((s) => s.orderIndex)).toEqual([0, 1])
  })

  it('clamps indent rather than corrupting a bullet', () => {
    let bullet = createBullet()
    for (let i = 0; i < 20; i += 1) bullet = indentBullet(bullet, 1)
    expect(bullet.level).toBe(2)

    for (let i = 0; i < 20; i += 1) bullet = indentBullet(bullet, -1)
    expect(bullet.level).toBe(0)
  })

  it('returns the identical object when an indent changes nothing', () => {
    const atFloor = createBullet()
    const atCeiling = createBullet({ level: 2 })
    expect(indentBullet(atFloor, -1)).toBe(atFloor)
    expect(indentBullet(atCeiling, 1)).toBe(atCeiling)
  })
})

describe('formatDurationRange — reversed, zero and absent ranges', () => {
  it.each([
    [null, null, 'Not specified'],
    [0, 0, 'Not specified'],
    [0, null, 'Not specified'],
    [null, 0, 'Not specified'],
    [30, 30, '30 min'],
    [30, null, '30 min'],
    [null, 90, 'up to 1 h 30 min'],
    [90, 30, '30 min – 1 h 30 min'],
    [60, 60, '1 h'],
    [-5, 90, 'up to 1 h 30 min'],
  ])('renders %s..%s as %s', (min, max, expected) => {
    expect(formatDurationRange(min, max)).toBe(expected)
  })

  it('never renders a bare number of minutes above an hour', () => {
    for (const minutes of [60, 61, 119, 120, 1440]) {
      expect(formatMinutes(minutes)).toMatch(/ h/)
    }
  })
})

describe('validateForPublish — what it lets through', () => {
  it('rejects a title that is only whitespace', () => {
    const issues = validateForPublish(guide({ title: '   \t\n ' }))
    expect(issues.map((issue) => issue.field)).toContain('title')
  })

  it('rejects a step whose bullets are all whitespace', () => {
    const issues = validateForPublish(
      guide({ steps: [step({ bullets: [createBullet({ text: '   ' })] })] }),
    )
    expect(issues.map((issue) => issue.field)).toContain('steps.0')
  })

  it('accepts a step that is only an image, with no words at all', () => {
    const withImage = step({
      bullets: [createBullet({ text: '' })],
      media: [{ id: 'm1', url: '/api/media/m1', alt: '', width: 1, height: 1, annotations: [] }],
    })
    expect(validateForPublish(guide({ steps: [withImage] }))).toEqual([])
  })

  /**
   * DEFECT (moderate): publish-time validation checks title, category and step
   * emptiness — src/domain/guide.ts:158-188 — but not the limits the server
   * enforces, so `Publish` can only discover them by failing. A title over 240
   * characters (backend/app/schemas.py:339), more than 50 tags
   * (MAX_TAGS_PER_GUIDE), or a minimum longer than the maximum
   * (`_assert_sane_time_range`, backend/app/documents.py:107-112) all pass the
   * client check and are then refused by the save that publishing performs
   * first — with a server sentence in a page-level red alert rather than a
   * message against the field that is wrong.
   */
  it.fails('catches the limits the server will refuse, before asking it', () => {
    const overlong = guide({
      title: 'x'.repeat(300),
      tags: Array.from({ length: 60 }, (_, i) => `tag-${i}`),
      timeRequiredMinMinutes: 90,
      timeRequiredMaxMinutes: 30,
    })

    const fields = validateForPublish(overlong).map((issue) => issue.field)
    expect(fields).toContain('title')
    expect(fields).toContain('tags')
    expect(fields).toContain('timeRequiredMinMinutes')
  })
})

import { describe, expect, it } from 'vitest'

import shared from '../../../backend/tests/data/tag_slug_cases.json'
import { slugifyTag } from './slug'

/**
 * The cases the server's own suite checks `tag_slug` against. Reading the same
 * file from both sides is what makes "the editor and the server agree" a fact
 * rather than a comment: a rule changed on one side alone fails that side.
 */
const cases = shared.cases as [string, string][]

describe('slugifyTag — the rule shared with the server', () => {
  it('has a meaningful number of shared cases', () => {
    expect(cases.length).toBeGreaterThan(20)
  })

  it.each(cases)('slugs %j as %j', (input, expected) => {
    expect(slugifyTag(input)).toBe(expected)
  })

  it('folds German letters to their readable spelling', () => {
    expect(slugifyTag('Präparation')).toBe('praeparation')
    expect(slugifyTag('Maßstab')).toBe('massstab')
  })

  it('leaves an existing slug where it is', () => {
    for (const text of ['Präparation', 'pr-paration', 'Grüne Fluoreszenz']) {
      expect(slugifyTag(slugifyTag(text))).toBe(slugifyTag(text))
    }
  })
})

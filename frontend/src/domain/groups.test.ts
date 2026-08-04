import { describe, expect, it } from 'vitest'

import { groupGuides, groupHeading } from './groups'
import { guideSummaryFixture } from '../test/fakeServer'

function guide(title: string, tags: string[]) {
  return guideSummaryFixture({ id: `g-${title}`, title, tags })
}

describe('groupGuides', () => {
  it('puts each guide under every tag it carries', () => {
    const startup = guide('Stellaris start-up', ['confocal', 'stellaris'])
    const shutdown = guide('Stellaris shutdown', ['confocal'])

    const { groups } = groupGuides([startup, shutdown])

    expect(groups.map((group) => group.tag)).toEqual(['confocal', 'stellaris'])
    expect(groups[0].guides.map((g) => g.title)).toEqual([
      'Stellaris start-up',
      'Stellaris shutdown',
    ])
    expect(groups[1].guides.map((g) => g.title)).toEqual(['Stellaris start-up'])
  })

  /**
   * The measured shape of ZMB's corpus: a fifth of guides belong to more than
   * one group, which is why one LAS X guide appears under ten instrument
   * headings. A grouping that showed each guide once would be a different site.
   */
  it('does not make a guide choose one of its tags', () => {
    const shared = guide('Booking a system', ['confocal', 'widefield', 'osd'])

    const { groups } = groupGuides([shared])

    expect(groups).toHaveLength(3)
    for (const group of groups) {
      expect(group.guides.map((g) => g.title)).toEqual(['Booking a system'])
    }
  })

  it('orders the groups alphabetically, not by whichever guide arrived first', () => {
    const { groups } = groupGuides([guide('One', ['widefield']), guide('Two', ['confocal'])])

    expect(groups.map((group) => group.tag)).toEqual(['confocal', 'widefield'])
  })

  it('keeps the listing’s order inside a group', () => {
    const { groups } = groupGuides([
      guide('Second', ['confocal']),
      guide('First', ['confocal']),
    ])

    expect(groups[0].guides.map((g) => g.title)).toEqual(['Second', 'First'])
  })

  /* An untagged guide is not put under a heading somebody would have to have
     invented, and it is not dropped either — which is the failure that matters,
     because a section nobody has finished tagging would simply look empty. */
  it('keeps an untagged guide, above the groups and under no heading', () => {
    const { loose, groups } = groupGuides([
      guide('Not tagged yet', []),
      guide('Tagged', ['confocal']),
    ])

    expect(loose.map((g) => g.title)).toEqual(['Not tagged yet'])
    expect(groups.map((group) => group.tag)).toEqual(['confocal'])
  })

  it('has nothing to say about a section with no guides', () => {
    expect(groupGuides([])).toEqual({ loose: [], groups: [] })
  })
})

describe('groupHeading', () => {
  it('raises the first letter of a tag and leaves the rest alone', () => {
    expect(groupHeading('nikonti2')).toBe('Nikonti2')
    expect(groupHeading('thunder')).toBe('Thunder')
    expect(groupHeading('z1scschlieren')).toBe('Z1scschlieren')
  })

  /* Not every word: `Carbon-On-Mica` is not how anybody writes it, and the CSS
     `capitalize` keyword does exactly that in some browsers and not others,
     which is why this is code rather than a stylesheet rule. */
  it('does not capitalise past the first letter', () => {
    expect(groupHeading('carbon-on-mica')).toBe('Carbon-on-mica')
    expect(groupHeading('data managment')).toBe('Data managment')
  })

  it('leaves a tag that already reads as a name untouched', () => {
    expect(groupHeading('GEInCell')).toBe('GEInCell')
  })

  it('has nothing to raise in an empty tag', () => {
    expect(groupHeading('')).toBe('')
  })
})

import { describe, expect, it } from 'vitest'

import { groupDocuments, groupHeading } from './groups'
import { guideSummaryFixture, pageSummaryFixture } from '../test/fakeServer'

function guide(title: string, tags: string[]) {
  return guideSummaryFixture({ id: `g-${title}`, title, tags })
}

function wiki(title: string, tags: string[]) {
  return pageSummaryFixture({ id: `w-${title}`, title, tags })
}

/** Titles in the order a group would draw them, whatever kind each row is. */
function titles(items: { kind: string; guide?: { title: string }; page?: { title: string } }[]) {
  return items.map((item) => (item.kind === 'guide' ? item.guide!.title : item.page!.title))
}

describe('groupDocuments', () => {
  it('puts each guide under every tag it carries', () => {
    const startup = guide('Stellaris start-up', ['confocal', 'stellaris'])
    const shutdown = guide('Stellaris shutdown', ['confocal'])

    const { groups } = groupDocuments([startup, shutdown], [])

    expect(groups.map((group) => group.tag)).toEqual(['confocal', 'stellaris'])
    expect(titles(groups[0].items)).toEqual(['Stellaris start-up', 'Stellaris shutdown'])
    expect(titles(groups[1].items)).toEqual(['Stellaris start-up'])
  })

  /**
   * The point of the whole change: a group is rows pointing at an endpoint, and
   * the endpoint is a guide or a wiki. The article about the Nikon belongs
   * beside the procedures for it rather than in a lump of articles at the top
   * of the page, which is where every wiki went while a page could not be
   * tagged.
   */
  it('gathers a wiki and a guide under the same tag', () => {
    const { groups } = groupDocuments(
      [guide('Nikon start-up', ['nikon'])],
      [wiki('About the Nikon', ['nikon'])],
    )

    expect(groups).toHaveLength(1)
    expect(titles(groups[0].items)).toEqual(['About the Nikon', 'Nikon start-up'])
    expect(groups[0].items.map((item) => item.kind)).toEqual(['wiki', 'guide'])
  })

  /* Reading before doing, at the scale the two now sit together. It used to be
     why the wikis were the first thing on the page; inside a group it is why
     they are the first rows of one. */
  it('puts the wikis in a group above its guides', () => {
    const { groups } = groupDocuments(
      [guide('First', ['nikon']), guide('Second', ['nikon'])],
      [wiki('Read me', ['nikon'])],
    )

    expect(titles(groups[0].items)).toEqual(['Read me', 'First', 'Second'])
  })

  /**
   * The measured shape of ZMB's corpus: a fifth of guides belong to more than
   * one group, which is why one LAS X guide appears under ten instrument
   * headings. A grouping that showed each guide once would be a different site.
   */
  it('does not make a guide choose one of its tags', () => {
    const shared = guide('Booking a system', ['confocal', 'widefield', 'osd'])

    const { groups } = groupDocuments([shared], [])

    expect(groups).toHaveLength(3)
    for (const group of groups) {
      expect(titles(group.items)).toEqual(['Booking a system'])
    }
  })

  it('does not make a wiki choose one of its tags either', () => {
    const { groups } = groupDocuments([], [wiki('Immersion oil', ['confocal', 'widefield'])])

    expect(groups.map((group) => group.tag)).toEqual(['confocal', 'widefield'])
    for (const group of groups) {
      expect(titles(group.items)).toEqual(['Immersion oil'])
    }
  })

  it('orders the groups alphabetically, not by whichever guide arrived first', () => {
    const { groups } = groupDocuments(
      [guide('One', ['widefield']), guide('Two', ['confocal'])],
      [],
    )

    expect(groups.map((group) => group.tag)).toEqual(['confocal', 'widefield'])
  })

  it('keeps the listing’s order inside a group', () => {
    const { groups } = groupDocuments(
      [guide('Second', ['confocal']), guide('First', ['confocal'])],
      [],
    )

    expect(titles(groups[0].items)).toEqual(['Second', 'First'])
  })

  /* An untagged document is not put under a heading somebody would have to have
     invented, and it is not dropped either — which is the failure that matters,
     because a section nobody has finished tagging would simply look empty. */
  it('keeps an untagged document, above the groups and under no heading', () => {
    const { loose, groups } = groupDocuments(
      [guide('Not tagged yet', []), guide('Tagged', ['confocal'])],
      [wiki('Nor this', [])],
    )

    expect(titles(loose)).toEqual(['Nor this', 'Not tagged yet'])
    expect(groups.map((group) => group.tag)).toEqual(['confocal'])
  })

  it('has nothing to say about an empty section', () => {
    expect(groupDocuments([], [])).toEqual({ loose: [], groups: [] })
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

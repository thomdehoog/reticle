import { describe, expect, it } from 'vitest'

import { pageSections } from './toc'

describe('pageSections', () => {
  it('lists the headings in the order they are written, with their depths', () => {
    const sections = pageSections(
      ['## Getting started', '', 'Some prose.', '', '### Booking', '', '## Rules'].join('\n'),
    )

    expect(sections.map((s) => s.text)).toEqual(['Getting started', 'Booking', 'Rules'])
    expect(sections.map((s) => s.depth)).toEqual([2, 3, 2])
  })

  it('gives every section an anchor a URL can carry', () => {
    const [section] = pageSections('## Getting started')
    expect(section.id).toBe('s-getting-started')
  })

  /** ZMB writes German. An anchor that dropped the umlauts would collide
      "Objektträger" with "Objekttrager" and read as neither. */
  it('keeps German letters in the anchor', () => {
    const [section] = pageSections('## Objektträger einlegen')
    expect(section.id).toBe('s-objektträger-einlegen')
  })

  /** Two sections may share a name — "Shutdown" under two instruments — and
      the second must still be reachable on its own. */
  it('tells duplicate headings apart', () => {
    const sections = pageSections(['## Shutdown', '', '## Shutdown'].join('\n'))
    expect(sections.map((s) => s.id)).toEqual(['s-shutdown', 's-shutdown-2'])
  })

  /** The one wrong way to find headings is a regex over the source: a code
      sample that merely shows a `#` line is not a section. */
  it('does not mistake a code sample for a heading', () => {
    const sections = pageSections(['```bash', '# not a heading', '```'].join('\n'))
    expect(sections).toEqual([])
  })

  /** The rail is a list of places, not an outline of every nuance. Three
      levels is where a column stops being one glance. */
  it('stops at the third level', () => {
    const sections = pageSections(['## Kept', '', '#### Too deep'].join('\n'))
    expect(sections.map((s) => s.text)).toEqual(['Kept'])
  })

  it('reads the words of a heading through its formatting', () => {
    const [section] = pageSections('## Using **LAS X** and `CAM`')
    expect(section.text).toBe('Using LAS X and CAM')
    expect(section.id).toBe('s-using-las-x-and-cam')
  })

  /** The category page already hands out `group-…` anchors, and the two kinds
      share the address bar. The prefix is what makes a clash impossible even
      for a heading that spells one out. */
  it('cannot collide with a group anchor', () => {
    const [section] = pageSections('## group-confocal')
    expect(section.id).toBe('s-group-confocal')
  })

  it('carries the source line each heading starts on', () => {
    const sections = pageSections(['Intro.', '', '## First', '', '## Second'].join('\n'))
    expect(sections.map((s) => s.line)).toEqual([3, 5])
  })

  it('answers nothing for a page with no headings', () => {
    expect(pageSections('Just prose, no structure.')).toEqual([])
    expect(pageSections('')).toEqual([])
  })
})

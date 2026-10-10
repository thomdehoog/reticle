import { describe, expect, it } from 'vitest'

import { guideListBlock, imageMarkdown, insertBlock, wrapSelection } from './markdownEdit'

describe('wrapSelection', () => {
  it('wraps the selected text and keeps it selected', () => {
    const edit = wrapSelection('Use oil here.', 4, 7, '**', '**', 'bold text')

    expect(edit.value).toBe('Use **oil** here.')
    expect(edit.value.slice(edit.selectionStart, edit.selectionEnd)).toBe('oil')
  })

  it('inserts a selected placeholder when nothing is selected', () => {
    const edit = wrapSelection('See .', 4, 4, '[', '](https://)', 'link text')

    expect(edit.value).toBe('See [link text](https://).')
    expect(edit.value.slice(edit.selectionStart, edit.selectionEnd)).toBe('link text')
  })
})

describe('insertBlock', () => {
  it('needs no leading break at the very start', () => {
    const edit = insertBlock('', 0, '## Heading')
    expect(edit.value).toBe('## Heading\n\n')
    expect(edit.selectionStart).toBe(edit.value.length)
  })

  it('separates the block from the text above with a blank line', () => {
    expect(insertBlock('Intro.', 6, '## Heading').value).toBe('Intro.\n\n## Heading\n\n')
  })

  it('does not add a second blank line when one is already there', () => {
    expect(insertBlock('Intro.\n\n', 8, '## Heading').value).toBe('Intro.\n\n## Heading\n\n')
  })

  it('inserts mid-document and leaves the cursor after the block', () => {
    const edit = insertBlock('Above.\n\nBelow.', 8, '- item')
    expect(edit.value).toBe('Above.\n\n- item\n\nBelow.')
    expect(edit.value.slice(edit.selectionStart)).toBe('Below.')
    expect(edit.selectionEnd).toBe(edit.selectionStart)
  })
})

describe('guideListBlock', () => {
  it('writes the fenced block the renderer reads', () => {
    expect(guideListBlock(['stellaris', 'confocal'], '  Confocal systems ')).toBe(
      '```guidelist\ntags: stellaris, confocal\nheading: Confocal systems\n```',
    )
  })

  it('leaves the heading line out when there is none', () => {
    expect(guideListBlock(['zen'], '   ')).toBe('```guidelist\ntags: zen\n```')
  })
})

describe('imageMarkdown', () => {
  it('writes an image reference', () => {
    expect(imageMarkdown('Objective turret', '/api/media/m1')).toBe(
      '![Objective turret](/api/media/m1)',
    )
  })

  it('keeps brackets in a filename from ending the alt text early', () => {
    expect(imageMarkdown('scan [final]', '/api/media/m1')).toBe('![scan  final](/api/media/m1)')
  })
})

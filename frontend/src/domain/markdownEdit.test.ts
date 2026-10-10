import { describe, expect, it } from 'vitest'

import {
  guideListBlock,
  imageMarkdown,
  insertBlock,
  insertImage,
  linkSelection,
  styleLines,
  wrapSelection,
} from './markdownEdit'

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

describe('insertBlock — spacing', () => {
  it('adds only the one line break that is missing', () => {
    expect(insertBlock('Intro.\n', 7, '- item').value).toBe('Intro.\n\n- item\n\n')
  })

  it('never leaves more than one blank line on either side', () => {
    expect(insertBlock('Above.\n\n\nBelow.', 8, '- item').value).toBe('Above.\n\n- item\n\nBelow.')
    expect(insertBlock('Above.\n\n\n\nBelow.', 8, '- item').value).toBe('Above.\n\n- item\n\nBelow.')
  })
})

describe('styleLines', () => {
  const selected = (edit: { value: string; selectionStart: number; selectionEnd: number }) =>
    edit.value.slice(edit.selectionStart, edit.selectionEnd)

  it('makes the line the cursor is in a heading, wherever in it the cursor sits', () => {
    const edit = styleLines('Intro.\nCleaning the objective\nMore.', 12, 12, 'heading')
    expect(edit.value).toBe('Intro.\n## Cleaning the objective\nMore.')
    expect(selected(edit)).toBe('## Cleaning the objective')
  })

  it('takes the marker off again when pressed twice', () => {
    const once = styleLines('Cleaning', 3, 3, 'heading')
    const twice = styleLines(once.value, once.selectionStart, once.selectionEnd, 'heading')
    expect(twice.value).toBe('Cleaning')
  })

  it('replaces a marker of another kind instead of stacking them', () => {
    expect(styleLines('- Cleaning', 4, 4, 'heading').value).toBe('## Cleaning')
    expect(styleLines('## Cleaning', 4, 4, 'subheading').value).toBe('### Cleaning')
    expect(styleLines('1. Cleaning', 4, 4, 'bullets').value).toBe('- Cleaning')
  })

  it('turns every selected line into a list item and numbers a numbered one', () => {
    const text = 'Air\nWater\nOil'
    expect(styleLines(text, 0, text.length, 'bullets').value).toBe('- Air\n- Water\n- Oil')
    expect(styleLines(text, 0, text.length, 'numbers').value).toBe('1. Air\n2. Water\n3. Oil')
  })

  it('leaves blank lines inside the selection alone, and out of the numbering', () => {
    expect(styleLines('Air\n\nOil', 0, 8, 'numbers').value).toBe('1. Air\n\n2. Oil')
  })

  it('starts a line with a placeholder to type over when there is nothing on it', () => {
    const edit = styleLines('Intro.\n\n', 8, 8, 'bullets')
    expect(edit.value).toBe('Intro.\n\n- List item')
    expect(selected(edit)).toBe('List item')
  })

  it('quotes and unquotes', () => {
    const quoted = styleLines('Do not press.', 0, 0, 'quote')
    expect(quoted.value).toBe('> Do not press.')
    expect(styleLines(quoted.value, 0, 0, 'quote').value).toBe('Do not press.')
  })
})

describe('linkSelection', () => {
  const selected = (edit: { value: string; selectionStart: number; selectionEnd: number }) =>
    edit.value.slice(edit.selectionStart, edit.selectionEnd)

  it('keeps selected words as the text and waits for the address', () => {
    const edit = linkSelection('See the booking rules.', 8, 21)
    expect(edit.value).toBe('See the [booking rules](https://).')
    expect(selected(edit)).toBe('https://')
  })

  it('keeps a selected address as the target and waits for the text', () => {
    const edit = linkSelection('https://www.zmb.uzh.ch', 0, 22)
    expect(edit.value).toBe('[link text](https://www.zmb.uzh.ch)')
    expect(selected(edit)).toBe('link text')
  })

  it('treats an in-app path as an address too', () => {
    expect(linkSelection('/w/booking-rules', 0, 16).value).toBe('[link text](/w/booking-rules)')
  })

  it('inserts a whole link to fill in when nothing is selected', () => {
    const edit = linkSelection('See .', 4, 4)
    expect(edit.value).toBe('See [link text](https://).')
    expect(selected(edit)).toBe('link text')
  })
})

describe('insertImage', () => {
  it('places the image as its own paragraph with the alt text selected', () => {
    const edit = insertImage('Intro.', 6, 'IMG_2041', '/api/media/m1')
    expect(edit.value).toBe('Intro.\n\n![IMG_2041](/api/media/m1)\n\n')
    expect(edit.value.slice(edit.selectionStart, edit.selectionEnd)).toBe('IMG_2041')
  })

  it('selects the right image when the same one is already in the page', () => {
    const existing = '![a](/api/media/m1)\n\nText.'
    const edit = insertImage(existing, existing.length, 'a', '/api/media/m1')
    expect(edit.selectionStart).toBeGreaterThan(existing.length)
    expect(edit.value.slice(edit.selectionStart, edit.selectionEnd)).toBe('a')
  })

  it('leaves the cursor between the brackets when the name gave no alt text', () => {
    const edit = insertImage('', 0, '[]', '/api/media/m1')
    expect(edit.value).toBe('![](/api/media/m1)\n\n')
    expect(edit.selectionStart).toBe(2)
    expect(edit.selectionEnd).toBe(2)
  })
})

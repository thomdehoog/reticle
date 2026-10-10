/**
 * Text operations behind the wiki editor's toolbar.
 *
 * Pure functions over a string and a selection, so the fiddly part — where the
 * markup goes and where the cursor ends up — can be tested without a textarea.
 */

export interface TextEdit {
  value: string
  selectionStart: number
  selectionEnd: number
}

/**
 * Wraps the selection in markup, or inserts a placeholder when nothing is
 * selected. The result selects the wrapped text, so typing replaces the
 * placeholder straight away.
 */
export function wrapSelection(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  before: string,
  after: string,
  placeholder: string,
): TextEdit {
  const selected = value.slice(selectionStart, selectionEnd) || placeholder
  return {
    value: value.slice(0, selectionStart) + before + selected + after + value.slice(selectionEnd),
    selectionStart: selectionStart + before.length,
    selectionEnd: selectionStart + before.length + selected.length,
  }
}

/**
 * Inserts a block — a table, an image, a guide list — as its own paragraph.
 * Markdown only recognises these when a blank line separates them from the
 * text on either side, so line breaks are added to make exactly one: none
 * where the author has already left a gap, and never a third.
 */
export function insertBlock(value: string, at: number, block: string): TextEdit {
  const before = value.slice(0, at)
  const after = value.slice(at)

  const breaksBefore = before.length - before.replace(/\n+$/, '').length
  const breaksAfter = after.length - after.replace(/^\n+/, '').length
  const lead = before === '' ? '' : '\n'.repeat(Math.max(0, 2 - breaksBefore))
  const trail = '\n'.repeat(Math.max(0, 2 - breaksAfter))

  const cursor = at + lead.length + block.length + trail.length
  return {
    value: before + lead + block + trail + after,
    selectionStart: cursor,
    selectionEnd: cursor,
  }
}

/** Builds a guide-list block so an author never types the fenced syntax. */
export function guideListBlock(tags: string[], heading: string): string {
  const lines = ['```guidelist', `tags: ${tags.join(', ')}`]
  if (heading.trim() !== '') lines.push(`heading: ${heading.trim()}`)
  lines.push('```')
  return lines.join('\n')
}

/**
 * Alt text may not contain the characters that would end the image syntax
 * early; a filename with a bracket in it is common enough to matter.
 */
export function imageMarkdown(alt: string, url: string): string {
  return `![${alt.replace(/[[\]\\]/g, ' ').trim()}](${url})`
}

export type LineStyle = 'heading' | 'subheading' | 'bullets' | 'numbers' | 'quote'

const LINE_PLACEHOLDERS: Record<LineStyle, string> = {
  heading: 'Heading',
  subheading: 'Subheading',
  bullets: 'List item',
  numbers: 'List item',
  quote: 'Quoted text',
}

/** Any marker one of the line buttons could have put there, so it can be replaced. */
const LINE_MARKER = /^(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s?)/

function markerFor(style: LineStyle, index: number): string {
  if (style === 'heading') return '## '
  if (style === 'subheading') return '### '
  if (style === 'bullets') return '- '
  if (style === 'numbers') return `${index + 1}. `
  return '> '
}

function hasMarker(style: LineStyle, line: string): boolean {
  if (style === 'heading') return /^##\s/.test(line)
  if (style === 'subheading') return /^###\s/.test(line)
  if (style === 'bullets') return /^[-*+]\s/.test(line)
  if (style === 'numbers') return /^\d+[.)]\s/.test(line)
  return /^>/.test(line)
}

/**
 * Turns the lines the selection touches into a heading, a list or a quote —
 * and back again if they already are one, so each button is a toggle.
 *
 * It works on whole lines wherever the cursor happens to sit in them, which is
 * what people expect from a "Heading" button: nobody selects from column zero
 * first. An existing marker of another kind is replaced rather than stacked,
 * so a bulleted line made into a heading does not become `## - text`.
 */
export function styleLines(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  style: LineStyle,
): TextEdit {
  const blockStart = value.lastIndexOf('\n', selectionStart - 1) + 1
  const nextBreak = value.indexOf('\n', selectionEnd)
  const blockEnd = nextBreak === -1 ? value.length : nextBreak
  const lines = value.slice(blockStart, blockEnd).split('\n')

  if (lines.every((line) => line.trim() === '')) {
    const marker = markerFor(style, 0)
    const placeholder = LINE_PLACEHOLDERS[style]
    const start = blockStart + marker.length
    return {
      value: value.slice(0, blockStart) + marker + placeholder + value.slice(blockEnd),
      selectionStart: start,
      selectionEnd: start + placeholder.length,
    }
  }

  const written = lines.filter((line) => line.trim() !== '')
  const removing = written.every((line) => hasMarker(style, line))

  let position = 0
  const rewritten = lines.map((line) => {
    if (line.trim() === '') return line
    const bare = line.replace(LINE_MARKER, '')
    return removing ? bare : markerFor(style, position++) + bare
  })

  const block = rewritten.join('\n')
  return {
    value: value.slice(0, blockStart) + block + value.slice(blockEnd),
    selectionStart: blockStart,
    selectionEnd: blockStart + block.length,
  }
}

const LINK_TEXT = 'link text'
const LINK_TARGET = 'https://'

/**
 * Makes a link, and leaves selected whichever half still has to be supplied.
 * Selected words become the link's text and the address is waiting to be typed
 * or pasted over; a selected address becomes the target and the text is.
 */
export function linkSelection(value: string, selectionStart: number, selectionEnd: number): TextEdit {
  const selected = value.slice(selectionStart, selectionEnd)
  const isAddress = /^(https?:\/\/|\/)\S+$/.test(selected)

  const text = selected === '' || isAddress ? LINK_TEXT : selected
  const target = isAddress ? selected : LINK_TARGET
  const inserted = `[${text}](${target})`

  const textStart = selectionStart + 1
  const targetStart = textStart + text.length + 2
  const selectTarget = selected !== '' && !isAddress

  return {
    value: value.slice(0, selectionStart) + inserted + value.slice(selectionEnd),
    selectionStart: selectTarget ? targetStart : textStart,
    selectionEnd: selectTarget ? targetStart + target.length : textStart + text.length,
  }
}

/**
 * Places an uploaded image as its own paragraph and selects its alt text.
 *
 * The alt text starts as the file's name, which is rarely a description —
 * "IMG_2041" tells a screen reader user nothing. Leaving it selected makes
 * replacing it the next thing the author types.
 */
export function insertImage(value: string, at: number, alt: string, url: string): TextEdit {
  const markdown = imageMarkdown(alt, url)
  const edit = insertBlock(value, at, markdown)
  const start = edit.value.indexOf(markdown, at) + 2
  const altLength = markdown.indexOf('](') - 2
  return { value: edit.value, selectionStart: start, selectionEnd: start + altLength }
}

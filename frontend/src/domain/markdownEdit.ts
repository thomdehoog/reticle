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
 * Inserts a block — a heading, a table, a guide list — as its own paragraph.
 * Markdown only recognises these when a blank line separates them from the
 * text above, so one is added unless it is already there.
 */
export function insertBlock(value: string, at: number, block: string): TextEdit {
  const needsLeadingBreak = at > 0 && !value.slice(0, at).endsWith('\n\n')
  const insertion = `${needsLeadingBreak ? '\n\n' : ''}${block}\n\n`
  const cursor = at + insertion.length
  return {
    value: value.slice(0, at) + insertion + value.slice(at),
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

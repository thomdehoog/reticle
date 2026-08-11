/**
 * The round-trip gate.
 *
 * The editor is a rendered view over the markdown the server stores, and the
 * one guarantee everything else rests on is that opening a page and closing it
 * again does not rewrite it. These tests parse markdown into the editor's
 * document and serialise it back, and hold the result to the source —
 * byte-identical where the vocabulary matches, semantically identical where
 * the serialiser normalises spelling (`_word_` and `*word*` are one meaning).
 *
 * The imported ZMB corpus is what is at stake: a page nobody touched must
 * never be re-serialised (the editor only reports real edits), and a page
 * somebody fixed a typo in must come back with everything else it held.
 */

import { Editor } from '@tiptap/core'
import { DOMParser as ProseMirrorDOMParser } from '@tiptap/pm/model'
import { describe, expect, it } from 'vitest'

import { wikiEditorExtensions } from './wikiEditorKit'

function editorWith(markdown: string): Editor {
  return new Editor({
    element: document.createElement('div'),
    extensions: wikiEditorExtensions(),
    content: markdown,
  })
}

function roundTrip(markdown: string): string {
  const editor = editorWith(markdown)
  const out = (
    editor.storage as unknown as { markdown: { getMarkdown(): string } }
  ).markdown.getMarkdown()
  editor.destroy()
  return out
}

describe('the wiki editor schema round-trips markdown', () => {
  it('keeps a page of headings, emphasis, lists and links as it was written', () => {
    const page = [
      '## Getting started',
      '',
      'A **bold** point and a [guide](/g/oil-immersion).',
      '',
      '- First',
      '- Second',
      '',
      '### Booking',
      '',
      '1. Sign in',
      '2. Pick a slot',
    ].join('\n')

    expect(roundTrip(page)).toBe(page)
  })

  /** The two fences are data, not prose. A serialiser that touched a byte of
      them would silently break the embed they describe. */
  it('keeps the guide fence byte for byte', () => {
    const fence = '```guide\noil-immersion\n```'
    expect(roundTrip(fence)).toBe(fence)
  })

  it('keeps the guide-list fence byte for byte', () => {
    const fence = '```guidelist\ntags: confocal, startup\nheading: Start-up\nlimit: 5\n```'
    expect(roundTrip(fence)).toBe(fence)
  })

  /** One meaning, one spelling on the way out. The rendered page is identical;
      only the delimiter is normalised, and only when the page is really edited
      does any of this reach the server. */
  it('normalises emphasis spelling without changing what it means', () => {
    expect(roundTrip('A _quiet_ word.')).toBe('A *quiet* word.')
  })

  it('keeps a table a table', () => {
    const table = [
      '| Information | Detail |',
      '| --- | --- |',
      '| Status | Vulnerable |',
    ].join('\n')

    const out = roundTrip(table)
    expect(out).toContain('| Information | Detail |')
    expect(out).toContain('| Status | Vulnerable |')
  })

  /** Imported bodies already carry pictures. The editor has no button for one
      yet, and the one wrong answer is to eat the ones that exist. */
  it('keeps an image a reader already sees', () => {
    const image = '![The entrance](/api/media/m-entrance)'
    expect(roundTrip(image)).toBe(image)
  })

  it('keeps a code sample with its language', () => {
    const sample = '```python\nprint("hello")\n```'
    expect(roundTrip(sample)).toBe(sample)
  })

  it('makes nothing from nothing', () => {
    expect(roundTrip('')).toBe('')
  })
})

/**
 * Where "no sanitiser" is earned. The schema is the whole list of what can
 * exist; anything pasted or inserted that is not in it does not survive into
 * the document, so the serialised markdown can never carry it to the server.
 */
describe('the wiki editor schema refuses what it does not know', () => {
  /**
   * The paste path. Pasting from Word or a web page hands the editor HTML,
   * and ProseMirror parses it against this schema: elements keep what has a
   * slot — the paragraph, the bold — and everything else has nowhere to
   * exist. Driven through the same DOM parser the paste handler uses,
   * because jsdom cannot synthesise a real clipboard event.
   */
  it('keeps the words of pasted HTML and drops its behaviour', () => {
    const editor = editorWith('')
    const pasted = document.createElement('div')
    pasted.innerHTML = '<p style="color:red" onclick="steal()">hi <b>bold</b></p>'
    const parsed = JSON.stringify(
      ProseMirrorDOMParser.fromSchema(editor.schema).parse(pasted).toJSON(),
    )
    editor.destroy()

    expect(parsed).toContain('hi')
    expect(parsed).toContain('bold')
    /* An attribute would only survive if the schema had a slot for it. */
    expect(parsed).not.toContain('onclick')
    expect(parsed).not.toContain('steal')
    expect(parsed).not.toContain('color:red')
  })

  it('lets no script element into a pasted document', () => {
    const editor = editorWith('')
    const pasted = document.createElement('div')
    pasted.innerHTML = '<p>before</p><script>alert(1)</script><p>after</p>'
    const parsed = JSON.stringify(
      ProseMirrorDOMParser.fromSchema(editor.schema).parse(pasted).toJSON(),
    )
    editor.destroy()

    expect(parsed).toContain('before')
    expect(parsed).toContain('after')
    expect(parsed).not.toContain('alert(1)')
  })

  /** HTML handed to `insertContent` as a string is read as markdown with
      `html: false`: the whole tag becomes escaped words in a paragraph.
      Nothing is executed and nothing becomes structure — the same answer the
      reader's renderer gives the same text. */
  it('reads an inserted HTML string as words', () => {
    const editor = editorWith('')
    editor.commands.insertContent('<p onclick="steal()">hi</p>')
    const types = editor.getJSON().content?.map((node) => node.type)
    editor.destroy()

    expect(types).toEqual(['paragraph'])
  })

  /** Raw HTML written into markdown source arrives as text, which is exactly
      what the reader's renderer does with it — the two agree that markup an
      author typed is words, not structure. */
  it('reads raw HTML in markdown as words, not structure', () => {
    const editor = editorWith('<div class="x">plain</div>')
    const types = editor.getJSON().content?.map((node) => node.type)
    editor.destroy()

    expect(types).not.toContain('div')
  })
})

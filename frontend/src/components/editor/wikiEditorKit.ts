/**
 * The wiki editor's vocabulary, and the markdown bridge.
 *
 * One list of what can exist in a page being edited: paragraphs, headings,
 * emphasis, lists, links, tables, images, code blocks and the blockquote and
 * rule markdown brings along. The list is the security boundary the renderer's
 * "no sanitiser" stance relies on — pasted content is parsed against this
 * schema and whatever has no slot here never becomes part of the document, so
 * the serialised markdown cannot carry it to the server.
 *
 * Markdown comes in and goes out through `tiptap-markdown`, with `html: false`
 * on both directions: raw HTML in a page's source is words to the reader's
 * renderer, and the editor has to read it the same way or the two would
 * disagree about what a page says.
 *
 * The code block is a parameter rather than a fixed entry because the fences
 * are data wearing a code block's syntax: the reading surface draws
 * ` ```guide `/` ```guidelist ` blocks as live embeds, and the editor does the
 * same through a node view — but a node view is a React presentation concern,
 * and this module is the schema, shared with headless round-trip tests that
 * have no React tree to mount one in.
 */

import type { AnyExtension } from '@tiptap/core'
import CodeBlock from '@tiptap/extension-code-block'
import Image from '@tiptap/extension-image'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import StarterKit from '@tiptap/starter-kit'
import { Markdown } from 'tiptap-markdown'

export function wikiEditorExtensions(options: { codeBlock?: AnyExtension } = {}): AnyExtension[] {
  return [
    StarterKit.configure({
      codeBlock: false,
      /* A link in the editing surface is being written, not followed — a click
         that navigated away mid-edit would take the draft's screen with it. */
      link: { openOnClick: false },
    }),
    options.codeBlock ?? CodeBlock,
    Table,
    TableRow,
    TableHeader,
    TableCell,
    Image,
    Markdown.configure({
      html: false,
      linkify: false,
      breaks: false,
    }),
  ]
}

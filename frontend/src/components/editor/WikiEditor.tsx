/**
 * The wiki page's writing surface.
 *
 * A page is edited looking exactly as it reads — the body rendered in the
 * reader's own typography, written in place — with one compact bar of controls
 * at the foot of the surface. The reference is Bear, not Word: no ribbon, no
 * panel of styles, one column of words.
 *
 * The markdown the server stores never stops being the real document. The
 * surface parses it on the way in and serialises it on the way out
 * (`wikiEditorKit`), and only a real edit reports anything: opening a page and
 * closing it again sends nothing, so an imported page nobody touched is never
 * re-serialised behind its author's back.
 *
 * The two fences — ` ```guide ` and ` ```guidelist ` — stay ordinary code
 * blocks in the document, which is what keeps their round-trip exact. They are
 * *drawn* as the live rows a reader would see, read-only: their insides are
 * data, and the dialogs that build them are the way to make one, not a cursor
 * inside the fence.
 */

import { useEffect, useRef, useState } from 'react'
import {
  EditorContent,
  NodeViewContent,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  useEditor,
  useEditorState,
  type Editor,
  type NodeViewProps,
} from '@tiptap/react'
import CodeBlock from '@tiptap/extension-code-block'

import { useApi } from '../../auth/AuthContext'
import type { GuideSummary } from '../../domain/types'
import { useAsync } from '../../hooks/useAsync'
import { HeaderMenu } from '../HeaderMenu'
import { GuideEmbed, GuideListEmbed } from '../MarkdownBody'
import { Modal } from '../ui'
import { TagInput } from './TagInput'
import { wikiEditorExtensions } from './wikiEditorKit'

/**
 * A code block that knows which of its languages are not code.
 *
 * The document model is untouched — same node, same attrs, same markdown out —
 * only the drawing changes: a guide or guide-list fence renders as the embed a
 * reader gets, and everything else stays a code sample with an editable
 * inside.
 */
const EmbedCodeBlock = CodeBlock.extend({
  addNodeView() {
    return ReactNodeViewRenderer(CodeBlockView)
  },
})

function CodeBlockView({ node }: NodeViewProps) {
  const language = (node.attrs.language as string | null) ?? ''

  if (language === 'guide' || language === 'guidelist') {
    return (
      /* No `NodeViewContent`: a view without a content hole is how ProseMirror
         is told the inside is not editable here. The block can still be
         selected, moved and deleted as one thing. */
      <NodeViewWrapper className="wiki-editor__embed" data-language={language}>
        {language === 'guide' ? (
          <GuideEmbed source={node.textContent} />
        ) : (
          <GuideListEmbed source={node.textContent} />
        )}
      </NodeViewWrapper>
    )
  }

  return (
    <NodeViewWrapper as="pre">
      <NodeViewContent<'code'> as="code" />
    </NodeViewWrapper>
  )
}

function markdownOf(editor: Editor): string {
  return (editor.storage as unknown as { markdown: { getMarkdown(): string } }).markdown.getMarkdown()
}

export function WikiEditor({
  value,
  onChange,
  onSourceView,
}: {
  /** The body as markdown — the same string the server stores. */
  value: string
  /** Fired with fresh markdown on every real edit, and never on mount. */
  onChange: (markdown: string) => void
  /** Offered in the bar's overflow so the raw markdown is never far away. */
  onSourceView?: () => void
}) {
  /* The newest markdown either side has seen. What tells an incoming `value`
     apart from the echo of this surface's own edit — without it, the autosave
     round-trip would reset the document under the caret. */
  const lastMarkdown = useRef(value)
  /* The editor is created once; the callback it reports to is not. */
  const onChangeRef = useRef(onChange)
  useEffect(() => {
    onChangeRef.current = onChange
  }, [onChange])

  const editor = useEditor({
    extensions: wikiEditorExtensions({ codeBlock: EmbedCodeBlock }),
    content: value,
    editorProps: {
      /* The reader's `.markdown` typography, on purpose: written in the shape
         it is read in is the whole promise of the surface. */
      attributes: { class: 'markdown wiki-editor__surface', 'aria-label': 'Page body' },
    },
    onUpdate({ editor }) {
      const markdown = markdownOf(editor)
      lastMarkdown.current = markdown
      onChangeRef.current(markdown)
    },
  })

  /* An external replacement — a conflict resolved with "use their version", an
     edit made in the source view — arrives as a new `value` this surface has
     not seen. It replaces the document without emitting: the author did not
     edit anything here, so nothing may be marked dirty on their behalf. */
  useEffect(() => {
    if (editor && value !== lastMarkdown.current) {
      lastMarkdown.current = value
      editor.commands.setContent(value, { emitUpdate: false })
    }
  }, [editor, value])

  return (
    <div className="wiki-editor">
      <EditorContent editor={editor} />
      {editor && <WikiEditorBar editor={editor} onSourceView={onSourceView} />}
    </div>
  )
}

/**
 * The bar at the foot of the surface.
 *
 * Everything an author reaches for while writing, one row: text style, bold
 * and italic, the two lists, a link, a guide, a table. The rarer inserts and
 * the table's own controls live behind the last button rather than widening
 * the row for everyone.
 */
export function WikiEditorBar({
  editor,
  onSourceView,
}: {
  editor: Editor
  onSourceView?: () => void
}) {
  const [menu, setMenu] = useState<'style' | 'more' | null>(null)
  const [dialog, setDialog] = useState<'link' | 'guide-link' | 'guide-embed' | 'guide-list' | null>(
    null,
  )

  const active = useEditorState({
    editor,
    selector: ({ editor }) => ({
      bold: editor.isActive('bold'),
      italic: editor.isActive('italic'),
      bulletList: editor.isActive('bulletList'),
      orderedList: editor.isActive('orderedList'),
      link: editor.isActive('link'),
      heading: editor.isActive('heading', { level: 2 }),
      subheading: editor.isActive('heading', { level: 3 }),
      table: editor.isActive('table'),
    }),
  })

  const styleName = active.heading ? 'Heading' : active.subheading ? 'Subheading' : 'Paragraph'

  function closeThen(run: () => void) {
    setMenu(null)
    run()
  }

  function insertFence(language: 'guide' | 'guidelist', spec: string) {
    editor
      .chain()
      .focus()
      .insertContent({
        type: 'codeBlock',
        attrs: { language },
        content: spec === '' ? undefined : [{ type: 'text', text: spec }],
      })
      .run()
  }

  return (
    <div className="wiki-editor__bar" role="toolbar" aria-label="Formatting">
      <HeaderMenu
        id="wiki-style-menu"
        className="header-menu--up"
        trigger={<>{styleName} ▾</>}
        triggerClassName="button button--sm"
        label="Text style"
        open={menu === 'style'}
        onOpen={() => setMenu('style')}
        onClose={() => setMenu(null)}
      >
        <button
          type="button"
          className="menu-item"
          onClick={() => closeThen(() => editor.chain().focus().setParagraph().run())}
        >
          Paragraph
        </button>
        <button
          type="button"
          className="menu-item"
          onClick={() => closeThen(() => editor.chain().focus().setHeading({ level: 2 }).run())}
        >
          Heading
        </button>
        <button
          type="button"
          className="menu-item"
          onClick={() => closeThen(() => editor.chain().focus().setHeading({ level: 3 }).run())}
        >
          Subheading
        </button>
      </HeaderMenu>

      <button
        type="button"
        className="button button--sm"
        aria-label="Bold"
        aria-pressed={active.bold}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <strong>B</strong>
      </button>
      <button
        type="button"
        className="button button--sm"
        aria-label="Italic"
        aria-pressed={active.italic}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        <em>I</em>
      </button>
      <button
        type="button"
        className="button button--sm"
        aria-label="Bulleted list"
        aria-pressed={active.bulletList}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        • List
      </button>
      <button
        type="button"
        className="button button--sm"
        aria-label="Numbered list"
        aria-pressed={active.orderedList}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        1. List
      </button>
      <button
        type="button"
        className="button button--sm"
        aria-pressed={active.link}
        onClick={() => setDialog('link')}
      >
        Link
      </button>
      <button type="button" className="button button--sm" onClick={() => setDialog('guide-link')}>
        Link a guide
      </button>
      <button
        type="button"
        className="button button--sm"
        disabled={active.table}
        onClick={() =>
          editor.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run()
        }
      >
        Table
      </button>

      <HeaderMenu
        id="wiki-more-menu"
        className="header-menu--up"
        trigger={<>⋯</>}
        triggerClassName="button button--sm"
        label="More"
        open={menu === 'more'}
        onOpen={() => setMenu('more')}
        onClose={() => setMenu(null)}
      >
        <button
          type="button"
          className="menu-item"
          onClick={() => closeThen(() => setDialog('guide-embed'))}
        >
          Insert one guide
        </button>
        <button
          type="button"
          className="menu-item"
          onClick={() => closeThen(() => setDialog('guide-list'))}
        >
          Insert guide list
        </button>
        {active.table && (
          <>
            <button
              type="button"
              className="menu-item"
              onClick={() => closeThen(() => editor.chain().focus().addRowAfter().run())}
            >
              Add row
            </button>
            <button
              type="button"
              className="menu-item"
              onClick={() => closeThen(() => editor.chain().focus().addColumnAfter().run())}
            >
              Add column
            </button>
            <button
              type="button"
              className="menu-item"
              onClick={() => closeThen(() => editor.chain().focus().deleteRow().run())}
            >
              Delete row
            </button>
            <button
              type="button"
              className="menu-item"
              onClick={() => closeThen(() => editor.chain().focus().deleteColumn().run())}
            >
              Delete column
            </button>
            <button
              type="button"
              className="menu-item"
              onClick={() => closeThen(() => editor.chain().focus().deleteTable().run())}
            >
              Delete table
            </button>
          </>
        )}
        {onSourceView && (
          <button type="button" className="menu-item" onClick={() => closeThen(onSourceView)}>
            Edit markdown source
          </button>
        )}
      </HeaderMenu>

      {dialog === 'link' && <LinkDialog editor={editor} onClose={() => setDialog(null)} />}
      {dialog === 'guide-link' && (
        <GuidePickerDialog
          title="Link a guide"
          hint="Inserts a link in the sentence being written, like any other link."
          onPick={(guide) => {
            /* `unsetMark` closes the link behind the caret: without it the
               link survives as a stored mark and the rest of the author's
               sentence quietly becomes part of it. */
            editor
              .chain()
              .focus()
              .insertContent({
                type: 'text',
                text: guide.title,
                marks: [{ type: 'link', attrs: { href: `/g/${guide.slug}` } }],
              })
              .unsetMark('link')
              .run()
            setDialog(null)
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'guide-embed' && (
        <GuidePickerDialog
          title="Insert one guide"
          hint="Shows the guide as the row it would be in any list."
          onPick={(guide) => {
            insertFence('guide', guide.slug)
            setDialog(null)
          }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'guide-list' && (
        <GuideListDialog
          onInsert={(spec) => {
            insertFence('guidelist', spec)
            setDialog(null)
          }}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  )
}

/**
 * One dialog for both moments a link is touched: making one, and standing in
 * one. Opened with a link under the caret it comes prefilled and offers
 * removal; opened on plain words it links them; opened on nothing it inserts
 * the words and the link in one go, because a link with no text to wear it is
 * nothing.
 */
function LinkDialog({ editor, onClose }: { editor: Editor; onClose: () => void }) {
  const existing = (editor.getAttributes('link').href as string | undefined) ?? ''
  const needsText = editor.state.selection.empty && existing === ''
  const [url, setUrl] = useState(existing)
  const [text, setText] = useState('')

  function apply() {
    const href = url.trim()
    if (href === '') return
    if (needsText) {
      /* As with the guide picker: close the link behind the caret, or the
         words typed after it join it. */
      editor
        .chain()
        .focus()
        .insertContent({
          type: 'text',
          text: text.trim() === '' ? href : text.trim(),
          marks: [{ type: 'link', attrs: { href } }],
        })
        .unsetMark('link')
        .run()
    } else {
      editor.chain().focus().extendMarkRange('link').setLink({ href }).run()
    }
    onClose()
  }

  function remove() {
    editor.chain().focus().extendMarkRange('link').unsetLink().run()
    onClose()
  }

  return (
    <Modal title="Link" onClose={onClose}>
      <div className="field">
        <label className="field__label" htmlFor="link-url">
          Address
        </label>
        <input
          id="link-url"
          className="input"
          autoFocus
          placeholder="https://… or /w/a-page-here"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              apply()
            }
          }}
        />
      </div>

      {needsText && (
        <div className="field">
          <label className="field__label" htmlFor="link-text">
            Words to carry it
          </label>
          <input
            id="link-text"
            className="input"
            placeholder="What the reader clicks"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      )}

      <div className="page-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={url.trim() === ''}
          onClick={apply}
        >
          {existing === '' ? 'Insert link' : 'Save link'}
        </button>
        {existing !== '' && (
          <button type="button" className="button button--danger" onClick={remove}>
            Remove link
          </button>
        )}
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

/**
 * Finds a guide by the words in its title, through the same search a reader
 * uses. Only guides are offered — a wiki page is linked with the ordinary link
 * dialog, by its address — and what "picking" one does belongs to the caller:
 * the same picker inserts a link in a sentence and a whole embedded row.
 */
function GuidePickerDialog({
  title,
  hint,
  onPick,
  onClose,
}: {
  title: string
  hint: string
  onPick: (guide: GuideSummary) => void
  onClose: () => void
}) {
  const api = useApi()
  const [term, setTerm] = useState('')

  const { data, error, loading } = useAsync(async () => {
    const query = term.trim()
    if (query === '') return []
    const results = await api.search(query)
    return results.flatMap((result) => (result.kind === 'guide' ? [result.guide] : []))
  }, [api, term])

  const guides = data ?? []

  return (
    <Modal title={title} onClose={onClose}>
      <p className="field__hint" style={{ marginBottom: '1rem' }}>
        {hint}
      </p>

      <div className="field">
        <label className="field__label" htmlFor="guide-picker-term">
          Search guides
        </label>
        <input
          id="guide-picker-term"
          className="input"
          autoFocus
          placeholder="Part of the guide’s title"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
        />
      </div>

      {error !== null && (
        <p className="field__hint" role="alert">
          The search did not answer. Try again in a moment.
        </p>
      )}
      {!loading && term.trim() !== '' && guides.length === 0 && error === null && (
        <p className="field__hint">No guide title matches “{term.trim()}”.</p>
      )}

      {guides.length > 0 && (
        <ul className="guide-picker">
          {guides.map((guide) => (
            <li key={guide.id}>
              <button type="button" className="guide-picker__row" onClick={() => onPick(guide)}>
                <span className="guide-picker__title">{guide.title}</span>
                {guide.summary && <span className="guide-picker__summary">{guide.summary}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="page-actions">
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

/**
 * Builds a guide-list's lines so an author never types the fenced syntax.
 * The block gathers every published guide carrying the tags and keeps itself
 * up to date; the fence around the lines is the caller's to add, because the
 * caller knows whether it is writing text or a document node.
 */
function GuideListDialog({
  onInsert,
  onClose,
}: {
  onInsert: (spec: string) => void
  onClose: () => void
}) {
  const [tags, setTags] = useState<string[]>([])
  const [heading, setHeading] = useState('')
  const [limit, setLimit] = useState('')

  function build(): string {
    const lines = [`tags: ${tags.join(', ')}`]
    if (heading.trim() !== '') lines.push(`heading: ${heading.trim()}`)
    const capped = Number.parseInt(limit, 10)
    if (Number.isFinite(capped) && capped > 0) lines.push(`limit: ${capped}`)
    return lines.join('\n')
  }

  return (
    <Modal title="Insert a guide list" onClose={onClose}>
      <p className="field__hint" style={{ marginBottom: '1rem' }}>
        Gathers every published guide carrying these tags, and keeps itself up to date.
      </p>

      <div className="field">
        <span className="field__label">Tags</span>
        <TagInput tags={tags} onChange={setTags} />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="guidelist-heading">
          Heading (optional)
        </label>
        <input
          id="guidelist-heading"
          className="input"
          value={heading}
          placeholder="e.g. Confocal systems"
          onChange={(event) => setHeading(event.target.value)}
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="guidelist-limit">
          Show at most (optional)
        </label>
        <input
          id="guidelist-limit"
          className="input"
          type="number"
          min={1}
          value={limit}
          placeholder="every matching guide"
          onChange={(event) => setLimit(event.target.value)}
        />
      </div>

      <div className="page-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={tags.length === 0}
          onClick={() => onInsert(build())}
        >
          Insert
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

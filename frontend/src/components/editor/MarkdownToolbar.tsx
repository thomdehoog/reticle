import { useRef, useState } from 'react'

import { IMAGE_ACCEPT } from '../../domain/media'
import {
  insertBlock,
  linkSelection,
  styleLines,
  wrapSelection,
  type TextEdit,
} from '../../domain/markdownEdit'
import { GuideListDialog } from './GuideListDialog'

/** Computes an edit from the text and the selection in it. */
export type BodyEdit = (value: string, selectionStart: number, selectionEnd: number) => TextEdit

interface MarkdownToolbarProps {
  /** Applies an edit to the page body and restores the cursor. */
  onEdit: (edit: BodyEdit) => void
  /** Uploads a picture and places it at the cursor. */
  onImage: (file: File) => void
  /** The share of the picture sent so far, 0–1, or null when none is uploading. */
  uploading: number | null
}

const TABLE = '| Column | Column |\n| --- | --- |\n| Value | Value |'

/** The formatting moves that also have a keyboard shortcut in the source box. */
export const BOLD: BodyEdit = (value, start, end) =>
  wrapSelection(value, start, end, '**', '**', 'bold text')
export const ITALIC: BodyEdit = (value, start, end) =>
  wrapSelection(value, start, end, '_', '_', 'italic text')
export const LINK: BodyEdit = linkSelection

/**
 * The buttons above the wiki source.
 *
 * They only ever produce Markdown text — the same text an author could type —
 * so the toolbar is a convenience and never a second way for content to exist.
 */
export function MarkdownToolbar({ onEdit, onImage, uploading }: MarkdownToolbarProps) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [insertingList, setInsertingList] = useState(false)

  const lines = (style: Parameters<typeof styleLines>[3]) => () =>
    onEdit((value, start, end) => styleLines(value, start, end, style))

  return (
    <div className="wiki-toolbar" role="toolbar" aria-label="Formatting">
      <div className="wiki-toolbar__group">
        <button type="button" className="button button--sm" onClick={lines('heading')}>
          Heading
        </button>
        <button type="button" className="button button--sm" onClick={lines('subheading')}>
          Subheading
        </button>
      </div>

      <div className="wiki-toolbar__group">
        <button
          type="button"
          className="button button--sm wiki-toolbar__bold"
          title="Bold (Ctrl+B)"
          onClick={() => onEdit(BOLD)}
        >
          Bold
        </button>
        <button
          type="button"
          className="button button--sm wiki-toolbar__italic"
          title="Italic (Ctrl+I)"
          onClick={() => onEdit(ITALIC)}
        >
          Italic
        </button>
        <button
          type="button"
          className="button button--sm"
          title="Link (Ctrl+K)"
          onClick={() => onEdit(LINK)}
        >
          Link
        </button>
      </div>

      <div className="wiki-toolbar__group">
        <button type="button" className="button button--sm" onClick={lines('bullets')}>
          List
        </button>
        <button type="button" className="button button--sm" onClick={lines('numbers')}>
          Numbered list
        </button>
        <button type="button" className="button button--sm" onClick={lines('quote')}>
          Quote
        </button>
        <button
          type="button"
          className="button button--sm"
          onClick={() => onEdit((value, start) => insertBlock(value, start, TABLE))}
        >
          Table
        </button>
      </div>

      <div className="wiki-toolbar__group">
        <button
          type="button"
          className="button button--sm"
          disabled={uploading !== null}
          onClick={() => fileRef.current?.click()}
        >
          {uploading === null ? 'Image' : `Uploading… ${Math.round(uploading * 100)}%`}
        </button>
        <button
          type="button"
          className="button button--sm button--primary"
          onClick={() => setInsertingList(true)}
        >
          Insert guide list
        </button>
      </div>

      <input
        ref={fileRef}
        type="file"
        accept={IMAGE_ACCEPT}
        aria-label="Upload an image"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onImage(file)
          event.target.value = ''
        }}
      />

      {insertingList && (
        <GuideListDialog
          onClose={() => setInsertingList(false)}
          onInsert={(block) => {
            setInsertingList(false)
            onEdit((value, start) => insertBlock(value, start, block))
          }}
        />
      )}
    </div>
  )
}

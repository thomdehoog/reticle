import { useRef, useState } from 'react'

import { imageMarkdown } from '../../domain/markdownEdit'
import { useUploadMedia } from '../../queries/media'
import { GuideListDialog } from './GuideListDialog'

interface MarkdownToolbarProps {
  /** Wraps the selection, or a placeholder when nothing is selected. */
  onWrap: (before: string, after: string, placeholder: string) => void
  /** Inserts a block as its own paragraph at the cursor. */
  onInsertBlock: (block: string) => void
  onError: (error: unknown) => void
}

/**
 * The buttons above the wiki source.
 *
 * They only ever produce Markdown text — the same text an author could type —
 * so the toolbar is a convenience and never a second way for content to exist.
 */
export function MarkdownToolbar({ onWrap, onInsertBlock, onError }: MarkdownToolbarProps) {
  const upload = useUploadMedia()
  const fileRef = useRef<HTMLInputElement>(null)
  const [insertingList, setInsertingList] = useState(false)

  /**
   * An image goes into the body as ordinary Markdown pointing at the upload.
   * The server reads those references on save, which is what later lets a
   * viewer fetch the picture once the page is published.
   */
  async function onPickImage(file: File | undefined) {
    if (!file) return
    onError(null)
    try {
      const media = await upload.mutateAsync(file)
      onInsertBlock(imageMarkdown(file.name.replace(/\.[^.]+$/, ''), media.url))
    } catch (cause) {
      onError(cause)
    }
  }

  return (
    <div className="wiki-toolbar">
      <button type="button" className="button button--sm" onClick={() => onInsertBlock('## Heading')}>
        Heading
      </button>
      <button
        type="button"
        className="button button--sm"
        onClick={() => onWrap('**', '**', 'bold text')}
      >
        Bold
      </button>
      <button
        type="button"
        className="button button--sm"
        onClick={() => onWrap('_', '_', 'italic text')}
      >
        Italic
      </button>
      <button
        type="button"
        className="button button--sm"
        onClick={() => onInsertBlock('- First item\n- Second item')}
      >
        List
      </button>
      <button
        type="button"
        className="button button--sm"
        onClick={() => onWrap('[', '](https://)', 'link text')}
      >
        Link
      </button>
      <button
        type="button"
        className="button button--sm"
        onClick={() => onInsertBlock('| Column | Column |\n| --- | --- |\n| Value | Value |')}
      >
        Table
      </button>
      <button
        type="button"
        className="button button--sm"
        disabled={upload.isPending}
        onClick={() => fileRef.current?.click()}
      >
        {upload.isPending ? 'Uploading…' : 'Image'}
      </button>
      <button
        type="button"
        className="button button--sm button--primary"
        onClick={() => setInsertingList(true)}
      >
        Insert guide list
      </button>

      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        aria-label="Upload an image"
        hidden
        onChange={(event) => {
          void onPickImage(event.target.files?.[0])
          event.target.value = ''
        }}
      />

      {insertingList && (
        <GuideListDialog
          onClose={() => setInsertingList(false)}
          onInsert={(block) => {
            onInsertBlock(block)
            setInsertingList(false)
          }}
        />
      )}
    </div>
  )
}

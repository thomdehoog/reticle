import type { ReactNode } from 'react'

import type { ContentStatus } from '../../domain/types'
import type { SaveState } from '../../hooks/useAutosave'
import type { DocumentAction } from '../../hooks/useDocumentActions'
import { StatusBadge } from '../ui'

const SAVE_LABELS: Record<SaveState, string> = {
  clean: 'All changes saved',
  pending: 'Unsaved changes…',
  saving: 'Saving…',
  saved: 'All changes saved',
  error: 'Could not save',
}

interface EditorHeaderProps {
  /** The trail to what is being edited, ending in a word for the editor itself. */
  breadcrumb: ReactNode
  title: string
  status: ContentStatus
  saveState: SaveState
  busy: DocumentAction | null
  /** A link to the published version, shown only while there is one. */
  viewLink: ReactNode
  /** A link to the publish history. */
  historyLink: ReactNode
  /** Archiving is an admin action; the server enforces it, this hides the button. */
  canArchive: boolean
  onPublish: () => void
  onUnpublish: () => void
  onArchive: () => void
}

/** The title bar both editors share: where you are, whether it is saved, what you can do. */
export function EditorHeader({
  breadcrumb,
  title,
  status,
  saveState,
  busy,
  viewLink,
  historyLink,
  canArchive,
  onPublish,
  onUnpublish,
  onArchive,
}: EditorHeaderProps) {
  const published = status === 'published'

  return (
    <div className="page-header">
      <div className="page-header__text">
        {breadcrumb}
        <h1>{title}</h1>
      </div>
      <div className="page-actions">
        <StatusBadge status={status} />
        {/* A live region that is always present: one that only appeared with
            its first message would not be announced. */}
        <span
          className={`save-state${saveState === 'error' ? ' save-state--error' : ''}`}
          role="status"
          aria-live="polite"
        >
          {SAVE_LABELS[saveState]}
        </span>
        {published && viewLink}
        {historyLink}
        {canArchive && (
          <button
            className="button button--danger"
            type="button"
            onClick={onArchive}
            disabled={busy !== null}
          >
            {busy === 'archiving' ? 'Archiving…' : 'Archive'}
          </button>
        )}
        {published && (
          <button className="button" type="button" onClick={onUnpublish} disabled={busy !== null}>
            {busy === 'unpublishing' ? 'Unpublishing…' : 'Unpublish'}
          </button>
        )}
        <button
          className="button button--primary"
          type="button"
          onClick={onPublish}
          disabled={busy !== null}
        >
          {busy === 'publishing' ? 'Publishing…' : published ? 'Publish update' : 'Publish'}
        </button>
      </div>
    </div>
  )
}

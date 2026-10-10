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
  /** How many times it has been published; the version readers have, if any. */
  version: number
  /** Whether the saved working copy differs from what readers have. */
  hasUnpublishedChanges: boolean
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
  onDiscard: () => void
  onArchive: () => void
}

/**
 * The title bar both editors share: where you are, whether it is saved, whether
 * readers have it, and what you can do.
 *
 * "Saved" and "published" are two different facts and the bar states both.
 * Saving is automatic and reaches only the working copy; an author who reads
 * "All changes saved" on a published guide must not take it to mean readers
 * have the changes, so the second fact is spelled out next to the first.
 */
export function EditorHeader({
  breadcrumb,
  title,
  status,
  version,
  hasUnpublishedChanges,
  saveState,
  busy,
  viewLink,
  historyLink,
  canArchive,
  onPublish,
  onUnpublish,
  onDiscard,
  onArchive,
}: EditorHeaderProps) {
  const published = status === 'published'
  /* Something typed and not yet saved is a change readers do not have either,
     whatever the server last said. */
  const unsaved = saveState === 'pending' || saveState === 'saving' || saveState === 'error'
  const ahead = published && (hasUnpublishedChanges || unsaved)

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
        {published && (
          <span className={`publish-state${ahead ? ' publish-state--ahead' : ''}`} role="status">
            {ahead
              ? `Unpublished changes — readers still see version ${version}`
              : `Readers see this version (${version})`}
          </span>
        )}
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
        {ahead && (
          <button className="button" type="button" onClick={onDiscard} disabled={busy !== null}>
            {busy === 'discarding' ? 'Discarding…' : 'Discard changes'}
          </button>
        )}
        <button
          className="button button--primary"
          type="button"
          onClick={onPublish}
          /* With nothing changed there is nothing to publish; a second copy of
             the same version in the history would only be noise. */
          disabled={busy !== null || (published && !ahead)}
          title={published && !ahead ? 'There are no changes to publish.' : undefined}
        >
          {busy === 'publishing' ? 'Publishing…' : published ? 'Publish update' : 'Publish'}
        </button>
      </div>
    </div>
  )
}

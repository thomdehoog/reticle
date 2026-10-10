/**
 * The pieces the guide and wiki history screens share.
 *
 * Every publish writes an immutable snapshot. These show the list of them and
 * mark a snapshot, when one is open, as exactly that — because a past version
 * drawn with the reader's own components looks, deliberately, just like the
 * real thing, and somebody will follow whatever procedure is on the screen.
 */

import type { ReactNode } from 'react'

import type { RevisionSummary } from '../api/reticle'
import { formatDate, formatDateTime } from '../domain/dates'
import { IconHistory } from './icons'
import { EmptyState } from './ui'

/** Newest first, whatever order the server sent them in. */
export function newestFirst(revisions: RevisionSummary[]): RevisionSummary[] {
  return [...revisions].sort((a, b) => b.version - a.version)
}

interface RevisionListProps {
  /** "guide" or "page", for the wording. */
  noun: string
  revisions: RevisionSummary[]
  /**
   * Wraps a row's content in the link to that version. Passed in because the
   * router's links are typed per route, and guides and pages live on different
   * ones.
   */
  renderLink: (revision: RevisionSummary, children: ReactNode) => ReactNode
}

export function RevisionList({ noun, revisions, renderLink }: RevisionListProps) {
  if (revisions.length === 0) {
    return (
      <EmptyState>
        This {noun} has not been published yet, so it has no history. A version is recorded each
        time it is published.
      </EmptyState>
    )
  }

  const ordered = newestFirst(revisions)

  return (
    <ol className="card revision-list" reversed>
      {ordered.map((revision, index) => (
        <li key={revision.version}>
          {renderLink(
            revision,
            <>
              <span className="revision-list__version">
                Version {revision.version}
                {index === 0 && <span className="badge badge--published">Latest</span>}
              </span>
              <span className="revision-list__meta">
                Published {formatDateTime(revision.publishedAt)} by{' '}
                {revision.publishedBy.displayName}
              </span>
            </>,
          )}
        </li>
      ))}
    </ol>
  )
}

interface RevisionBannerProps {
  revision: RevisionSummary
  /** False for the newest snapshot, which is not "old" — only frozen. */
  superseded: boolean
  /** Links back to the history list and on to the live document. */
  children: ReactNode
}

export function RevisionBanner({ revision, superseded, children }: RevisionBannerProps) {
  return (
    <div className="revision-banner" role="note">
      <IconHistory size={18} />
      <p className="revision-banner__text">
        <strong>
          Version {revision.version}, published {formatDate(revision.publishedAt)}
        </strong>{' '}
        by {revision.publishedBy.displayName} —{' '}
        {superseded
          ? 'not the current version.'
          : 'the most recent published version, shown as it was when it was published.'}
      </p>
      <div className="revision-banner__actions">{children}</div>
    </div>
  )
}

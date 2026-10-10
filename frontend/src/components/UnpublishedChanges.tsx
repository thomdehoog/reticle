/**
 * What an author is told when a published guide or page has been edited since.
 *
 * Saving is not publishing: readers keep the last published version until
 * somebody publishes again. The reader screens therefore show an author that
 * same published version by default, and these two notices are how the author
 * learns that newer work exists and gets to it.
 *
 * A viewer never sees either. The server tells a viewer that nothing is
 * pending, whatever the truth, so the condition that draws these is false.
 */

import type { ReactNode } from 'react'

import { IconEdit } from './icons'

interface NoticeProps {
  /** "guide" or "page", or a phrase like "landing page", for the wording. */
  noun: string
  /** The version readers are being shown. */
  version: number
  /** Links, already pointing where they should; this only arranges them. */
  children: ReactNode
}

/**
 * On the published version: quiet, because what is on screen is correct and
 * complete — it is simply not the newest thing the author has written.
 */
export function UnpublishedChangesNotice({ noun, version, children }: NoticeProps) {
  return (
    <div className="alert alert--info changes-notice" role="note">
      <p className="changes-notice__text">
        <strong>This {noun} has unpublished changes.</strong> Readers see version {version}, shown
        here.
      </p>
      <div className="changes-notice__actions">{children}</div>
    </div>
  )
}

/**
 * On the working copy shown in the reader: loud, and it stays in view. This
 * looks exactly like the published guide and is not it, which is the same
 * hazard a past version poses and gets the same banner.
 */
export function PreviewBanner({ noun, version, children }: NoticeProps) {
  return (
    <div className="revision-banner" role="note">
      <IconEdit />
      <p className="revision-banner__text">
        <strong>Preview of unpublished changes.</strong> This is the working copy of the {noun};
        readers still see version {version}.
      </p>
      <div className="revision-banner__actions">{children}</div>
    </div>
  )
}

/** The small label a list puts on something whose working copy is ahead. */
export function UnpublishedBadge() {
  return <span className="badge badge--changes">Unpublished changes</span>
}

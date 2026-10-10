import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { DIFFICULTY_LABELS, formatDurationRange } from '../domain/guide'
import type { GuideSummary, PageSummary } from '../domain/types'
import { StatusBadge } from './ui'

/**
 * One guide in a list. Draft status is shown so authors can spot their own work.
 *
 * `edit` sends the row to the editor instead of the reader — for a list of
 * unfinished work, where reading is not what the author came to do.
 */
export function GuideRow({ guide, edit = false }: { guide: GuideSummary; edit?: boolean }) {
  const body: ReactNode = (
    <>
      <div className="guide-row__main">
        <div className="guide-row__title">{guide.title}</div>
        {guide.summary && <div className="guide-row__summary">{guide.summary}</div>}
        <div className="guide-row__meta">
          <span>
            {guide.stepCount} {guide.stepCount === 1 ? 'step' : 'steps'}
          </span>
          <span>{DIFFICULTY_LABELS[guide.difficulty]}</span>
          <span>
            {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
          </span>
          <span>{guide.author.displayName}</span>
        </div>
      </div>
      {guide.status !== 'published' && <StatusBadge status={guide.status} />}
    </>
  )

  return edit ? (
    <Link className="guide-row" to="/g/$id/edit" params={{ id: guide.id }}>
      {body}
    </Link>
  ) : (
    <Link className="guide-row" to="/g/$slug" params={{ slug: guide.slug }}>
      {body}
    </Link>
  )
}

/** A wiki page in a list. Labelled, because "guide" and "page" behave differently. */
export function PageRow({ page }: { page: PageSummary }) {
  return (
    <Link className="guide-row" to="/w/$slug" params={{ slug: page.slug }}>
      <div className="guide-row__main">
        <div className="guide-row__title">{page.title}</div>
        {page.summary && <div className="guide-row__summary">{page.summary}</div>}
        <div className="guide-row__meta">
          <span className="result-kind">Wiki page</span>
          {page.isLanding && <span>Category landing page</span>}
        </div>
      </div>
      {page.status !== 'published' && <StatusBadge status={page.status} />}
    </Link>
  )
}

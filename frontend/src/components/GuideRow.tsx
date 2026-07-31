import { Link } from 'react-router-dom'

import { DIFFICULTY_LABELS, formatDuration } from '../domain/guide'
import type { GuideSummary } from '../domain/types'
import { StatusBadge } from './ui'

/** One guide in a list. Draft status is shown so authors can spot their own work. */
export function GuideRow({ guide, to }: { guide: GuideSummary; to?: string }) {
  return (
    <Link className="guide-row" to={to ?? `/g/${guide.slug}`}>
      <div className="guide-row__main">
        <div className="guide-row__title">{guide.title}</div>
        {guide.summary && <div className="guide-row__summary">{guide.summary}</div>}
        <div className="guide-row__meta">
          <span>
            {guide.stepCount} {guide.stepCount === 1 ? 'step' : 'steps'}
          </span>
          <span>{DIFFICULTY_LABELS[guide.difficulty]}</span>
          <span>{formatDuration(guide.timeRequiredMinutes)}</span>
          <span>{guide.author.displayName}</span>
        </div>
      </div>
      {guide.status !== 'published' && <StatusBadge status={guide.status} />}
    </Link>
  )
}

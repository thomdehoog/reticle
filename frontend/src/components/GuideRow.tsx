import { Link } from '@tanstack/react-router'

import { formatDate } from '../domain/dates'
import { DIFFICULTY_LABELS, formatDurationRange } from '../domain/guide'
import type { GuideSummary, PageSummary } from '../domain/types'
import { TagLink } from './TagLink'
import { StatusBadge } from './ui'
import { UnpublishedBadge } from './UnpublishedChanges'

/** A guide may carry thirty tags; a row shows the first few and counts the rest. */
const TAGS_SHOWN = 4

/**
 * One guide in a list. Draft status is shown so authors can spot their own
 * work, and so is a published guide whose working copy has moved on — the
 * title and tags an author sees listed are the working copy's, and the badge
 * is what says readers are not seeing them yet.
 *
 * The whole row is the target for the guide — its title link is stretched over
 * the row in CSS — while the tag chips stay links of their own on top of it.
 * A row that was one big anchor could not hold them: a link inside a link is
 * not valid HTML, and browsers pull such markup apart.
 *
 * `edit` sends the row to the editor instead of the reader — for a list of
 * unfinished work, where reading is not what the author came to do.
 */
export function GuideRow({ guide, edit = false }: { guide: GuideSummary; edit?: boolean }) {
  const hiddenTags = guide.tags.length - TAGS_SHOWN

  return (
    <div className="guide-row">
      <div className="guide-row__main">
        {edit ? (
          <Link className="guide-row__title" to="/g/$id/edit" params={{ id: guide.id }}>
            {guide.title || 'Untitled guide'}
          </Link>
        ) : (
          <Link className="guide-row__title" to="/g/$slug" params={{ slug: guide.slug }}>
            {guide.title || 'Untitled guide'}
          </Link>
        )}
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
        {guide.tags.length > 0 && (
          <div className="guide-row__tags">
            {guide.tags.slice(0, TAGS_SHOWN).map((tag) => (
              <TagLink key={tag} slug={tag} />
            ))}
            {hiddenTags > 0 && <span className="guide-row__more">+{hiddenTags} more</span>}
          </div>
        )}
      </div>
      {guide.status !== 'published' && <StatusBadge status={guide.status} />}
      {guide.hasUnpublishedChanges && <UnpublishedBadge />}
    </div>
  )
}

/** A wiki page in a list. Labelled, because "guide" and "page" behave differently. */
export function PageRow({ page, categoryName }: { page: PageSummary; categoryName?: string }) {
  return (
    <div className="guide-row">
      <div className="guide-row__main">
        <Link className="guide-row__title" to="/w/$slug" params={{ slug: page.slug }}>
          {page.title || 'Untitled page'}
        </Link>
        {page.summary && <div className="guide-row__summary">{page.summary}</div>}
        <div className="guide-row__meta">
          <span className="result-kind">Wiki page</span>
          {page.isLanding && <span>Category landing page</span>}
          {categoryName && !page.isLanding && <span>In {categoryName}</span>}
          <span>Updated {formatDate(page.updatedAt)}</span>
        </div>
      </div>
      {page.status !== 'published' && <StatusBadge status={page.status} />}
      {page.hasUnpublishedChanges && <UnpublishedBadge />}
    </div>
  )
}

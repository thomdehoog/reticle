/**
 * The visual index: how somebody gets to a guide or a wiki page.
 *
 * Every one of these is a picture first and a label second, because that is how
 * the material is actually navigated. A list of titles makes a reader parse
 * thirty lines of prose to find the instrument they are standing in front of;
 * a wall of pictures lets them recognise it. So the wording on a card is held
 * to what identifies the destination — the rest of the sentence belongs on the
 * page it leads to, where somebody has decided to read.
 *
 * The three shapes correspond to the three things there are to reach: a
 * section, a wiki page, and a guide.
 */

import { Link } from 'react-router'

import { DIFFICULTY_LABELS, formatDurationRange } from '../domain/guide'
import type { Category, GuideSummary, PageSummary } from '../domain/types'
import { IconBook, IconSteps } from './icons'
import { Thumbnail } from './Thumbnail'
import { StatusBadge } from './ui'

/** A section. The count is the only number worth carrying on the way in. */
export function CategoryTile({
  category,
  guideCount,
  childCount,
}: {
  category: Category
  guideCount: number
  childCount?: number
}) {
  return (
    <Link className="tile" to={`/c/${category.slug}`}>
      <Thumbnail seed={category.name} src={category.imageUrl} className="tile__media" />
      <span className="tile__body">
        <span className="tile__name">{category.name}</span>
        <span className="tile__meta">
          {childCount ? `${childCount} sections · ` : ''}
          {guideCount} {guideCount === 1 ? 'guide' : 'guides'}
        </span>
      </span>
      {category.isHidden && <span className="tile__flag">Hidden</span>}
    </Link>
  )
}

/**
 * A guide. The picture is its first step image, so the card shows the thing the
 * guide starts by showing you.
 */
export function GuideCard({ guide, to }: { guide: GuideSummary; to?: string }) {
  return (
    <Link className="tile tile--guide" to={to ?? `/g/${guide.slug}`}>
      <Thumbnail seed={guide.title} src={guide.thumbnailUrl} className="tile__media" />
      <span className="tile__body">
        <span className="tile__name">{guide.title}</span>
        <span className="tile__meta">
          <IconSteps size={13} />
          <span>
            {guide.stepCount} {guide.stepCount === 1 ? 'step' : 'steps'}
          </span>
          <span className="tile__dot" aria-hidden="true">
            ·
          </span>
          <span>{DIFFICULTY_LABELS[guide.difficulty]}</span>
          {(guide.timeRequiredMinMinutes !== null || guide.timeRequiredMaxMinutes !== null) && (
            <>
              <span className="tile__dot" aria-hidden="true">
                ·
              </span>
              <span>
                {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
              </span>
            </>
          )}
        </span>
      </span>
      {guide.status !== 'published' && (
        <span className="tile__status">
          <StatusBadge status={guide.status} />
        </span>
      )}
    </Link>
  )
}

/**
 * A wiki page. Landing pages are marked, because they are a section's front.
 *
 * `context` is the section it belongs to, shown where the card is seen away
 * from that section — on the wiki index, a page's own title rarely says which
 * instrument it is about.
 */
export function WikiCard({ page, context }: { page: PageSummary; context?: string | null }) {
  return (
    <Link className="tile tile--wiki" to={`/w/${page.slug}`}>
      <Thumbnail seed={page.title} src={page.heroImageUrl} className="tile__media" />
      <span className="tile__body">
        <span className="tile__name">{page.title}</span>
        <span className="tile__meta">
          <IconBook size={13} />
          <span>{page.isLanding ? 'Section front page' : 'Wiki page'}</span>
          {context && (
            <>
              <span className="tile__dot" aria-hidden="true">
                ·
              </span>
              <span>{context}</span>
            </>
          )}
        </span>
      </span>
      {page.status !== 'published' && (
        <span className="tile__status">
          <StatusBadge status={page.status} />
        </span>
      )}
    </Link>
  )
}

/** The grid every one of them sits in. */
export function TileGrid({ children }: { children: React.ReactNode }) {
  return <div className="tiles">{children}</div>
}

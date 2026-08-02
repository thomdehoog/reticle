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

import { formatDurationRange } from '../domain/guide'
import type { Category, GuideSummary, PageSummary } from '../domain/types'
import { IconBook } from './icons'
import { Thumbnail } from './Thumbnail'
import { DifficultyMeter, StatusBadge } from './ui'

/**
 * A section: the picture and its name.
 *
 * No count under it. "12 guides" never decided which section somebody opened —
 * they came for the confocal — and "0 guides" under a section that is being
 * filled in reads as broken rather than as new. The only mark left is the one
 * that changes what the tile means: a holding section, which is reached by tag
 * rather than by browsing, and which only an author ever sees.
 */
export function CategoryTile({ category }: { category: Category }) {
  return (
    <Link className="tile" to={`/c/${category.slug}`}>
      <Thumbnail seed={category.name} src={category.imageUrl} className="tile__media" />
      <span className="tile__body">
        <span className="tile__name">{category.name}</span>
      </span>
      {category.isHidden && <span className="tile__flag">Hidden</span>}
    </Link>
  )
}

/**
 * A guide. The picture is its first step image, so the card shows the thing the
 * guide starts by showing you.
 *
 * This is the big shape, and it is now used only where a guide is the subject
 * rather than one of a list — an author's own unfinished work on the front page.
 * Inside a section, where the answer to "which of these eight" is the title,
 * `GuideRow` shows five in the space this takes for one.
 */
export function GuideCard({ guide, to }: { guide: GuideSummary; to?: string }) {
  return (
    <Link className="tile tile--guide" to={to ?? `/g/${guide.slug}`}>
      <Thumbnail seed={guide.title} src={guide.thumbnailUrl} className="tile__media" />
      <span className="tile__body">
        <span className="tile__name">{guide.title}</span>
        <span className="tile__meta">
          <DifficultyMeter difficulty={guide.difficulty} />
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
 * A guide in a list of guides: the title, and its first step image beside it.
 *
 * Under an instrument heading there are typically eight of these and the reader
 * already knows which instrument they are looking at, so the thing that tells
 * them apart is the title — which means the title gets the width and the picture
 * gets a corner of it. Five fit on a phone screen where five cards would have
 * been five screens of scrolling.
 *
 * The thumbnail is decorative here: the link is already named by its title, and
 * a screen reader announcing the first step's image before the title would put
 * a description of a photograph between the reader and the name of the
 * procedure.
 */
export function GuideRow({ guide, to }: { guide: GuideSummary; to?: string }) {
  return (
    <Link className="guide-row" to={to ?? `/g/${guide.slug}`}>
      <span className="guide-row__main">
        <span className="guide-row__title">{guide.title}</span>
        <span className="guide-row__meta">
          <DifficultyMeter difficulty={guide.difficulty} />
          <span>
            {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
          </span>
          {guide.status !== 'published' && <StatusBadge status={guide.status} />}
        </span>
      </span>
      <Thumbnail seed={guide.title} src={guide.thumbnailUrl} className="guide-row__thumb" />
    </Link>
  )
}

/** The list a run of rows sits in, so they read as one block with one border. */
export function GuideRows({ children }: { children: React.ReactNode }) {
  return <div className="guide-rows">{children}</div>
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
        {/* The heading above the group already says these are wiki pages, so a
            card only speaks when it has something the group does not: that it is
            a section's front rather than an article, or — where the card is seen
            away from its section — which section it belongs to. With neither,
            the line is dropped rather than left as a lone icon. */}
        {(page.isLanding || context) && (
          <span className="tile__meta">
            <IconBook size={13} />
            {page.isLanding && <span>Section front page</span>}
            {context && <span>{context}</span>}
          </span>
        )}
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

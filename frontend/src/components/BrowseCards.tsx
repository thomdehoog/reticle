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

import type { Category, GuideSummary, PageSummary } from '../domain/types'
import { IconBook, IconEdit, IconPlus, IconTrash } from './icons'
import { Thumbnail } from './Thumbnail'
import { StatusBadge } from './ui'

/**
 * A section: the picture and its name.
 *
 * No count under it. "12 guides" never decided which section somebody opened —
 * they came for the confocal — and "0 guides" under a section that is being
 * filled in reads as broken rather than as new. The only mark left is the one
 * that changes what the tile means: a holding section, which is reached by tag
 * rather than by browsing, and which only an author ever sees.
 *
 * An administrator gets two more: edit and delete, in the tile's own corner.
 * They sit on the tile rather than on a screen of their own because the tile is
 * where somebody is already looking when they notice the picture is wrong —
 * and they are small and quiet, because a reader's eye should still land on the
 * photograph. `onDelete` absent means the controls are not drawn at all, which
 * is how everyone who is not an administrator sees this.
 *
 * The buttons are siblings of the link, not children of it: a button inside an
 * anchor is invalid, and both browsers and screen readers make their own guess
 * about what a click on it meant.
 */
export function CategoryTile({
  category,
  onDelete,
  draggable = false,
  emptyToReaders = false,
}: {
  category: Category
  /** Given only to an administrator; its absence is what hides the controls. */
  onDelete?: (category: Category) => void
  draggable?: boolean
  /**
   * Nothing published under it, so a reader is not shown this tile at all.
   *
   * Only an administrator ever sees one of these, and only because a section
   * they have just made would otherwise vanish. The mark is the honest half of
   * that: the tile is here, and it is not yet anybody else's.
   */
  emptyToReaders?: boolean
}) {
  return (
    <div className={`tile-holder${draggable ? ' tile-holder--draggable' : ''}`}>
      <Link className="tile" to={`/c/${category.slug}`}>
        <Thumbnail seed={category.name} src={category.imageUrl} className="tile__media" />
        <span className="tile__body">
          <span className="tile__name">{category.name}</span>
        </span>
        {category.isHidden && <span className="tile__flag">Hidden</span>}
        {!category.isHidden && emptyToReaders && <span className="tile__flag">Empty</span>}
      </Link>

      {onDelete && (
        <div className="tile-tools">
          <Link
            className="tile-tools__button"
            to={`/categories/${category.id}/edit`}
            aria-label={`Edit ${category.name}`}
            title={`Edit ${category.name}`}
          >
            <IconEdit size={15} />
          </Link>
          <button
            className="tile-tools__button tile-tools__button--danger"
            type="button"
            aria-label={`Delete ${category.name}`}
            title={`Delete ${category.name}`}
            onClick={() => onDelete(category)}
          >
            <IconTrash size={15} />
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The tile that makes a section, wearing the same shape as the ones that open
 * them.
 *
 * It is a tile and not a button above the grid because that is where the eye
 * already is, and because it answers the question an empty facility asks: a
 * site with no sections at all showed a line of text saying so, which tells an
 * administrator what is wrong and not what to do about it. This is the same
 * control in both cases — the last tile in a full grid, and the only tile in an
 * empty one.
 */
export function NewCategoryTile({ parentId }: { parentId?: string | null }) {
  const to = parentId ? `/categories/new?parent=${encodeURIComponent(parentId)}` : '/categories/new'
  return (
    <div className="tile-holder">
      <Link className="tile tile--new" to={to}>
        <span className="tile__media tile__media--new" aria-hidden="true">
          <IconPlus size={30} />
        </span>
        <span className="tile__body">
          <span className="tile__name">Add a section</span>
        </span>
      </Link>
    </div>
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
 * A wiki page as a row, for the list of them on a section.
 *
 * The same row as a guide's rather than the card used on the wiki index,
 * because on a section the two lists sit one above the other and a reader
 * comparing them should be reading one kind of thing in two groups, not two
 * kinds of furniture. What the wiki list is *called* is what says which is
 * which; the rows do not need to differ to make that point.
 *
 * It says nothing about being a landing page: a section's own front page is
 * not listed inside that section, so the only pages here are its articles.
 */
export function PageRow({ page }: { page: PageSummary }) {
  return (
    <Link className="guide-row" to={`/w/${page.slug}`}>
      <span className="guide-row__main">
        <span className="guide-row__title">{page.title}</span>
        <span className="guide-row__meta">
          {page.status !== 'published' && <StatusBadge status={page.status} />}
        </span>
      </span>
      <Thumbnail seed={page.title} src={page.heroImageUrl} className="guide-row__thumb" />
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

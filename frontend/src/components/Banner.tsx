/**
 * The picture across the top of the front page and of every category.
 *
 * It answers one question — where am I — with a photograph rather than a
 * sentence, which is the whole argument for it. A microscopist arriving at
 * Light Microscopy recognises the field of cells before they have read the
 * heading, and a facility whose documentation is mostly images should look like
 * one from the first screen.
 *
 * It carries the title and at most one line of context. The platform this
 * replaces put five lines here, two of them explaining how to sign in, and
 * nobody read past the second visit. One line is the budget.
 *
 * It is a separate file because the same banner is used at three levels — the
 * facility, a category, a sub-category — and the moment it is copied into two
 * pages the two drift, which is how a site starts feeling like several sites.
 *
 * The banner's title is the page's only ``h1``. Pages render this instead of
 * their own heading rather than as well as it.
 */

import { DrawnFigure } from './Thumbnail'

export interface BannerProps {
  /** The heading, and the page's only ``h1``. */
  title: string
  /** One line of context. Omitted rather than emptied when there is none. */
  line?: string | null
  /** The photograph. Falls back to a drawn figure when absent. */
  src?: string | null
  /**
   * Taller on the front page than inside a category: arriving at the facility
   * is the one moment worth a whole screen, and by the time somebody is two
   * levels down they know where they are and want the guides.
   */
  variant?: 'facility' | 'section'
}

export function Banner({ title, line, src, variant = 'section' }: BannerProps) {
  return (
    <section className={`banner banner--${variant}`}>
      <div className="banner__art">
        {src ? (
          <img className="banner__image" src={src} alt="" />
        ) : (
          /* The same drawn cover the tiles use, so a category with no
             photograph looks unfinished in neither place. No monogram, unlike
             the tiles: on a tile the letters stand in for a name that is
             underneath in small type, and here the name is already across the
             picture in the largest type on the screen. */
          <DrawnFigure seed={title} />
        )}
      </div>
      <div className="banner__text">
        <h1 className="banner__title">{title}</h1>
        {line && <p className="banner__line">{line}</p>}
      </div>
    </section>
  )
}

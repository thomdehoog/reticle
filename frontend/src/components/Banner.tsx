/**
 * The picture across the top of the front page and of every category.
 *
 * It answers one question — where am I — with a photograph rather than a
 * sentence, which is the whole argument for it. A microscopist arriving at
 * Light Microscopy recognises the field of cells before they have read the
 * heading, and a facility whose documentation is mostly images should look like
 * one from the first screen.
 *
 * The picture is shown twice: once whole, on a plate at the left, and once
 * enlarged and darkened behind everything. The plate is there because these are
 * micrographs and line drawings composed to be looked at — a photograph cropped
 * to a letterbox and dimmed until text sits on it is a photograph nobody can
 * read. The backdrop is there because the plate alone leaves a band of flat
 * colour belonging to no section in particular, and because the room or the
 * specimen carrying on past the plate's edges is what makes the band this
 * section's rather than decoration. It is darkened, not hidden.
 *
 * The title sits at the top of the plate, not beside its middle, and the
 * introduction runs under the title. A heading centred against the picture
 * floats at whatever height the text below it happens to push it to, so no two
 * sections' banners begin in the same place.
 *
 * The introduction is a short paragraph, not a page. The platform this replaces
 * put five lines here, two of them explaining how to sign in, and nobody read
 * past the second visit. Two or three sentences is the budget.
 *
 * It is a separate file because the same banner is used at three levels — the
 * facility, a category, a sub-category — and the moment it is copied into two
 * pages the two drift, which is how a site starts feeling like several sites.
 *
 * Those three and no more: a guide and a wiki page do not get one. Weighed and
 * decided rather than never reached. Those two are the bottom of the tree, and
 * the bottom of the tree is where the information actually is — the banner
 * marks the levels somebody is still choosing between, and at the level they
 * chose, the procedure starts at the top of the screen. A third of it spent
 * saying where they already know they are is a third taken from step one, on
 * the one screen read standing at an instrument.
 *
 * A guide could not have a good one in any case: it has no picture of its own,
 * its picture *is* its first step image, so the banner would show that
 * photograph and then show it again a few hundred pixels below.
 *
 * The banner's title is the page's only ``h1``. Pages render this instead of
 * their own heading rather than as well as it.
 */

import { DrawnFigure } from './Thumbnail'

export interface BannerProps {
  /** The heading, and the page's only ``h1``. */
  title: string
  /**
   * The short introduction under the title. Omitted rather than emptied when
   * there is none, so a section nobody has written one for shows a title
   * against its picture instead of a gap where a paragraph should be.
   */
  intro?: string | null
  /** The photograph. Falls back to a drawn figure when absent. */
  src?: string | null
  /**
   * Taller on the front page than inside a category: arriving at the facility
   * is the one moment worth a whole screen, and by the time somebody is two
   * levels down they know where they are and want the guides.
   */
  variant?: 'facility' | 'section'
}

export function Banner({ title, intro, src, variant = 'section' }: BannerProps) {
  /* The same drawn cover the tiles use, so a category with no photograph looks
     unfinished in neither place. No monogram, unlike the tiles: on a tile the
     letters stand in for a name that is underneath in small type, and here the
     name is already across the picture in the largest type on the screen. */
  const picture = src ? <img className="banner__image" src={src} alt="" /> : <DrawnFigure seed={title} />

  return (
    <section className={`banner banner--${variant}`}>
      {/* The backdrop is the plate's picture again, and it is built from the
          same expression rather than from a second branch: a section whose
          plate shows drawn artwork and whose backdrop showed flat blue would be
          two answers to one question, and the pairing would come apart the
          first time either side gained a case the other did not. */}
      <div className="banner__backdrop" aria-hidden="true">
        {picture}
      </div>

      <div className="banner__inner">
        <div className="banner__plate">{picture}</div>
        <div className="banner__text">
          <h1 className="banner__title">{title}</h1>
          {intro && <p className="banner__intro">{intro}</p>}
        </div>
      </div>
    </section>
  )
}

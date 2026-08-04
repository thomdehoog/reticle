/**
 * The handful of guides that answer the question most people arrive with.
 *
 * Booking an instrument, getting into the building, finding where the data
 * went: procedures nobody would think to look for under a microscope's name,
 * and the ones a facility is asked about most. An author marks a guide as a
 * quick link and it appears here, under the sections on the front page.
 *
 * The front page only. It used to appear on every section with sub-sections as
 * well, which put the same four procedures under a third of the site: a section
 * shows one kind of thing, and a shortcut to somewhere else is not that kind.
 * Arriving is the moment for a shortcut past the tree; being three levels into
 * the tree is not.
 *
 * The block is laid out wide — a badge-sized picture with the title and one
 * line beside it — so that a row of them cannot be mistaken for more
 * categories. That is also why the heading stays when everything else lost its
 * caption: without it these read as a second, stranger grid.
 *
 * It fetches its own listing rather than being handed one, because the two
 * screens that show it have nothing else in common and neither of them wants
 * to know that quick links are guides.
 */

import { Link } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { Thumbnail } from './Thumbnail'
import { StatusBadge } from './ui'

export function QuickLinks() {
  const api = useApi()
  const { data } = useAsync(() => api.listGuides({ quickLink: true }), [api])
  /* The filter is the server's job and it is asked for. The flag is checked
     again here because the failure mode of a listing that ignored the filter is
     the whole corpus presented as the four things people ask for most, which is
     worse on this screen than showing none. */
  const guides = (data ?? []).filter((guide) => guide.isQuickLink)

  /* Nothing to show is not an empty state, and a listing that failed is not an
     error banner: these are a shortcut to material the tree below already
     reaches, so a facility that has marked none of them — or a request that did
     not come back — simply has a shorter front page. */
  if (guides.length === 0) return null

  return (
    <section className="section">
      <h2 className="section__title section__title--caption">Quick links</h2>
      <div className="quick-links">
        {guides.map((guide) => (
          <Link className="qlink" key={guide.id} to={`/g/${guide.slug}`}>
            <Thumbnail seed={guide.title} src={guide.thumbnailUrl} className="qlink__art" />
            <span className="qlink__text">
              <span className="qlink__name">{guide.title}</span>
              {(guide.summary !== '' || guide.status !== 'published') && (
                <span className="qlink__sub">
                  {guide.status !== 'published' && <StatusBadge status={guide.status} />}
                  <span className="qlink__summary">{guide.summary}</span>
                </span>
              )}
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

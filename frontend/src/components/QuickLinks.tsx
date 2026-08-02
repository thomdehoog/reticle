/**
 * The handful of guides that answer the question most people arrive with.
 *
 * Booking an instrument, getting into the building, finding where the data
 * went: procedures nobody would think to look for under a microscope's name,
 * and the ones a facility is asked about most. An author marks a guide as a
 * quick link and it appears here, above the tree, on the front page and on
 * every category that has sub-categories.
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
  const guides = data ?? []

  /* Nothing to show is not an error and not an empty state: a facility that has
     not marked any quick links yet simply has a shorter front page. */
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
                  {guide.summary}
                </span>
              )}
            </span>
          </Link>
        ))}
      </div>
    </section>
  )
}

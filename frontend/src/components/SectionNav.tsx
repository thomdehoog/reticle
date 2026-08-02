/**
 * What else is in this section, shown beside what you are reading.
 *
 * A procedure is rarely read alone. Somebody starting the confocal reads the
 * start-up guide, then wants the one about choosing an objective, then the
 * shutdown — and without this they went back to the section, found their place
 * again, and clicked in a second time for each of them. The whole group is on
 * the left instead, with the current item marked, so moving between the
 * procedures for one instrument costs one click.
 *
 * Both content types are listed together because both are the section: the wiki
 * pages carry the background and the guides carry the steps, and which one
 * holds the answer is not something a reader knows in advance.
 */

import { Link } from 'react-router'

import type { GuideSummary, PageSummary } from '../domain/types'
import { IconBook, IconSteps } from './icons'

export interface SectionNavProps {
  /** The section these belong to, and where its own page lives. */
  section: { name: string; slug: string } | null
  pages: PageSummary[]
  guides: GuideSummary[]
  /** The identifier of whatever is being read, so it can be marked. */
  currentId: string
}

function NavItem({
  to,
  label,
  current,
  icon,
}: {
  to: string
  label: string
  current: boolean
  icon: React.ReactNode
}) {
  return (
    <li>
      <Link
        className={`section-nav__item${current ? ' section-nav__item--current' : ''}`}
        to={to}
        aria-current={current ? 'page' : undefined}
      >
        <span className="section-nav__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="section-nav__label">{label}</span>
      </Link>
    </li>
  )
}

export function SectionNav({ section, pages, guides, currentId }: SectionNavProps) {
  const articles = pages.filter((page) => !page.isLanding)

  /* Nothing to move between: one item is the thing already open, and a list of
     it is furniture rather than navigation. */
  if (articles.length + guides.length <= 1) return null

  return (
    <nav className="section-nav" aria-label={section ? `More in ${section.name}` : 'More in this section'}>
      <div className="section-nav__head">
        {section ? (
          <Link className="section-nav__section" to={`/c/${section.slug}`}>
            {section.name}
          </Link>
        ) : (
          <span className="section-nav__section">Wiki</span>
        )}
      </div>

      {articles.length > 0 && (
        <>
          <h2 className="section-nav__group">Pages</h2>
          <ul className="section-nav__list">
            {articles.map((page) => (
              <NavItem
                key={page.id}
                to={`/w/${page.slug}`}
                label={page.title}
                current={page.id === currentId}
                icon={<IconBook size={13} />}
              />
            ))}
          </ul>
        </>
      )}

      {guides.length > 0 && (
        <>
          <h2 className="section-nav__group">Guides</h2>
          <ul className="section-nav__list">
            {guides.map((guide) => (
              <NavItem
                key={guide.id}
                to={`/g/${guide.slug}`}
                label={guide.title}
                current={guide.id === currentId}
                icon={<IconSteps size={13} />}
              />
            ))}
          </ul>
        </>
      )}
    </nav>
  )
}

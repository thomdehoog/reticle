/**
 * The dark column down the left of every wide screen.
 *
 * It carries the two things a reader needs at all times and nowhere else to put
 * them: where they can go — Home, the wiki, the tags — and where they are, as a
 * list of the places at their own level of the tree. Standing at an instrument
 * with a procedure open, "which of the other confocal systems has a guide for
 * this" is one glance rather than two page loads.
 *
 * It is its own file rather than part of `AppShell` because it is the piece
 * with a rule in it. The shell arranges boxes; this decides which places to
 * list, and that decision is the whole navigation model: the browsable
 * categories at the front, and once you are inside a category, the sub-
 * categories of the level you are standing on. Everything else about the shell
 * would be harder to read with that reasoning threaded through it.
 *
 * Below the phone breakpoint it is not rendered at all. A 236px column on a
 * 390px screen is not a rail, it is the screen — the same list goes in the
 * drawer the header's one button opens.
 */

import type { ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router'

import { useAuth } from '../auth/AuthContext'
import type { Category } from '../domain/types'
import { useBrowsableCategories } from '../hooks/useCategories'
import { IconBook, IconHome, IconTag, ReticleMark } from './icons'

/** The places listed under the heading, and what the heading calls them. */
export interface Places {
  heading: string
  places: Category[]
  /** The one being read, marked by weight and a bar rather than by colour. */
  currentId: string | null
}

function byOrder(categories: Category[]): Category[] {
  return [...categories].sort(
    (a, b) => a.orderIndex - b.orderIndex || a.name.localeCompare(b.name),
  )
}

/**
 * Which places belong in the rail, given where the reader is.
 *
 * One level at a time, because a tree with every branch open is a filing
 * cabinet: at the front the categories, inside a category its sub-categories,
 * and inside a sub-category its siblings — which is the list somebody comparing
 * two instruments actually wants. A category with nothing under it has no level
 * of its own to show, so it falls back to the front's list with itself marked.
 *
 * It is given the browsable categories rather than all of them, and the rule
 * that makes them browsable is `browsableCategories`. The rail has to offer the
 * same places the tiles do: a category the front page has hidden, listed here,
 * is the dead end back again with a shorter name.
 */
export function railPlaces(browsable: Category[], slug: string | null): Places {
  const current = slug === null ? undefined : browsable.find((c) => c.slug === slug)
  const childrenOf = (id: string) => byOrder(browsable.filter((c) => c.parentId === id))

  if (current) {
    const children = childrenOf(current.id)
    if (children.length > 0) return { heading: current.name, places: children, currentId: null }

    const parent = browsable.find((c) => c.id === current.parentId)
    if (parent) {
      return { heading: parent.name, places: childrenOf(parent.id), currentId: current.id }
    }
  }

  return {
    heading: 'Categories',
    places: byOrder(browsable.filter((c) => c.parentId === null)),
    currentId: current?.id ?? null,
  }
}

/** The slug of the category being read, or null anywhere else in the app. */
function categorySlug(pathname: string): string | null {
  const match = pathname.match(/^\/c\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

/**
 * The heading and the list under it, drawn the same in the rail and in the
 * phone drawer — they are the same list, and a reader who learns it on a
 * desktop should find it in the same words in their hand.
 *
 * Nothing is shown while the categories are still coming: the rail is
 * furniture, and a column that flickers on every navigation is worse than one
 * that fills in a moment later. Whatever went wrong is reported by the page.
 */
export function RailPlaces() {
  const { pathname } = useLocation()
  const { data: browsable } = useBrowsableCategories()
  const { heading, places, currentId } = railPlaces(browsable ?? [], categorySlug(pathname))

  if (places.length === 0) return null

  return (
    <>
      <hr className="rail__rule" />
      <h2 className="rail__section">{heading}</h2>
      <div className="rail__places">
        {places.map((place) => (
          <Link
            key={place.id}
            className={`rail__item${place.id === currentId ? ' rail__item--on' : ''}`}
            to={`/c/${place.slug}`}
            aria-current={place.id === currentId ? 'page' : undefined}
          >
            {place.name}
          </Link>
        ))}
      </div>
    </>
  )
}

/**
 * `account` is the signed-in person at the foot. It arrives as a prop because
 * the panel it opens is one of the shell's menus, and only one of those may be
 * open at a time — a rule that has to live where all of them can see it.
 */
export function SideRail({ account }: { account: ReactNode }) {
  const { organisation } = useAuth()

  return (
    <nav className="rail" aria-label="Sections">
      <Link className="rail__brand" to="/">
        <ReticleMark />
        Reticle
      </Link>
      {organisation && <span className="rail__facility">{organisation.name}</span>}

      <div className="rail__nav">
        <NavLink className="rail__link" to="/" end>
          <IconHome size={17} />
          Home
        </NavLink>
        <NavLink className="rail__link" to="/w">
          <IconBook size={17} />
          Wiki
        </NavLink>
        <NavLink className="rail__link" to="/t">
          <IconTag size={17} />
          Tags
        </NavLink>
      </div>

      <RailPlaces />

      <div className="rail__spacer" />
      {account}
    </nav>
  )
}

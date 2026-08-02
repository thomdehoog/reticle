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
 * list, and that decision is the whole navigation model: the rail descends with
 * the reader, one level at a time, from the categories at the front down to the
 * guides themselves. Everything else about the shell would be harder to read
 * with that reasoning threaded through it.
 *
 * Below the phone breakpoint it is not rendered at all. A 236px column on a
 * 390px screen is not a rail, it is the screen — the same list goes in the
 * drawer the header's one button opens.
 */

import { useState, type ReactNode } from 'react'
import { Link, NavLink, useLocation } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import type { Category, GuideSummary, PageSummary } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { useBrowsableCategories } from '../hooks/useCategories'
import { IconBook, IconHome, IconTag, ReticleMark } from './icons'

/**
 * One row of the rail: a category, a guide or a wiki page.
 *
 * `slug` sits beside `id` because the URL carries whichever the author linked
 * with, and the rail marks what is open by matching the address in the bar.
 */
export interface RailPlace {
  id: string
  slug: string
  name: string
  to: string
}

/** What a category holds directly — the bottom of the tree, as the rail lists it. */
export interface CategoryContents {
  guides: GuideSummary[]
  pages: PageSummary[]
}

/** The places listed under the heading, and what the heading calls them. */
export interface Places {
  heading: string
  /** Where the heading leads, or null at the front, which is not a place. */
  headingTo: string | null
  places: RailPlace[]
  /** The one being read, marked by weight and a bar rather than by colour. */
  currentId: string | null
}

function byOrder(categories: Category[]): Category[] {
  return [...categories].sort(
    (a, b) => a.orderIndex - b.orderIndex || a.name.localeCompare(b.name),
  )
}

function categoryPlace(category: Category): RailPlace {
  return {
    id: category.id,
    slug: category.slug,
    name: category.name,
    to: `/c/${category.slug}`,
  }
}

/**
 * A category's own documents, in the order the category's page lists them.
 *
 * Guides before wiki pages, which is the order the screen puts them in, and no
 * grouping of its own: where the guides are grouped under instrument headings
 * that grouping lives in the landing page's guide-list blocks, and a rail that
 * invented a second arrangement of the same procedures would leave a reader
 * unable to trust either. One order, from the same listing, in both places.
 *
 * The landing page is left out because it is not something inside the category
 * — it is the category, and the heading above this list already leads there.
 */
function contentsPlaces(contents: CategoryContents): RailPlace[] {
  return [
    ...contents.guides.map((guide) => ({
      id: guide.id,
      slug: guide.slug,
      name: guide.title,
      to: `/g/${guide.slug}`,
    })),
    ...contents.pages
      .filter((page) => !page.isLanding)
      .map((page) => ({ id: page.id, slug: page.slug, name: page.title, to: `/w/${page.slug}` })),
  ]
}

/**
 * Which places belong in the rail, given where the reader is.
 *
 * One level at a time, because a tree with every branch open is a filing
 * cabinet. The rule is stated in terms of where somebody is standing rather
 * than how deep they have gone, so there is no arithmetic on levels anywhere in
 * it: a category with browsable children lists those children, and a category
 * without them is the bottom of the tree and lists what it holds. A category
 * that goes straight to its guides is an ordinary shape and not a special case
 * — at ZMB, Electron Microscopy is one and Light Microscopy is not.
 *
 * Reading a guide or a page is standing in the category that holds it, so the
 * rail shows that same list with the one being read marked. Which is what makes
 * the second navigation column beside a guide unnecessary: this is that list.
 *
 * `contents` is null while the category's documents are still on their way, and
 * an empty category has nothing of its own to show either. Both fall back to
 * the level above with the category marked, so the column always answers "where
 * am I" with something true rather than going blank and filling in later.
 *
 * It is given the browsable categories rather than all of them, and the rule
 * that makes them browsable is `browsableCategories`. The rail has to offer the
 * same places the tiles do: a category the front page has hidden, listed here,
 * is the dead end back again with a shorter name.
 */
export function railPlaces(
  browsable: Category[],
  slug: string | null,
  contents: CategoryContents | null,
  /** The guide or page in the address bar, by slug or id, or null. */
  reading: string | null,
): Places {
  const current = slug === null ? undefined : browsable.find((c) => c.slug === slug)
  const childrenOf = (id: string) => byOrder(browsable.filter((c) => c.parentId === id))

  if (current) {
    const children = childrenOf(current.id)
    if (children.length > 0) {
      return {
        heading: current.name,
        headingTo: `/c/${current.slug}`,
        places: children.map(categoryPlace),
        currentId: null,
      }
    }

    const inside = contents === null ? [] : contentsPlaces(contents)
    if (inside.length > 0) {
      const open =
        reading === null
          ? undefined
          : inside.find((place) => place.id === reading || place.slug === reading)
      return {
        heading: current.name,
        headingTo: `/c/${current.slug}`,
        places: inside,
        currentId: open?.id ?? null,
      }
    }

    const parent = browsable.find((c) => c.id === current.parentId)
    if (parent) {
      return {
        heading: parent.name,
        headingTo: `/c/${parent.slug}`,
        places: childrenOf(parent.id).map(categoryPlace),
        currentId: current.id,
      }
    }
  }

  return {
    heading: 'Categories',
    headingTo: null,
    places: byOrder(browsable.filter((c) => c.parentId === null)).map(categoryPlace),
    currentId: current?.id ?? null,
  }
}

/** The slug of the category being read, or null anywhere else in the app. */
function categorySlug(pathname: string): string | null {
  const match = pathname.match(/^\/c\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

/** The guide or wiki page being read, so the rail can find its category. */
function documentPath(pathname: string): { kind: 'guide' | 'page'; key: string } | null {
  const guide = pathname.match(/^\/g\/([^/]+)/)
  if (guide) return { kind: 'guide', key: decodeURIComponent(guide[1]) }
  const page = pathname.match(/^\/w\/([^/]+)/)
  if (page) return { kind: 'page', key: decodeURIComponent(page[1]) }
  return null
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
  const api = useApi()
  const { data: browsable } = useBrowsableCategories()

  /*
   * Reading a guide is being somewhere. The rail knew that on a category page
   * and nowhere else, so opening a procedure left the column showing the whole
   * institute with nothing marked — the two questions it exists to answer,
   * where am I and what is beside me, both went unanswered exactly when a
   * reader is deepest in.
   *
   * The category is not in the path, so it is asked for. One request, only on
   * the screens that need it.
   */
  const here = documentPath(pathname)
  const { data: within } = useAsync(async () => {
    if (!here) return { categoryId: null }
    /* A document that will not load is somewhere the rail cannot place, and the
       page beside it already says so; the column goes quietly back to the
       front's list rather than reporting the same failure twice. */
    const document = await (here.kind === 'guide'
      ? api.getGuide(here.key)
      : api.getPage(here.key)
    ).catch(() => null)
    return { categoryId: document?.categoryId ?? null }
  }, [api, here?.kind, here?.key])

  /*
   * The section the reader is standing in, held across the moment a document
   * has been asked for and has not arrived.
   *
   * Stepping from one procedure to the next in a section re-fetches the guide,
   * and for that moment nothing in the path or in hand says which category it
   * belongs to. Without the held answer the column emptied of its neighbours,
   * showed the list of categories, and filled back in — twice a click, on the
   * one screen a reader spends real time on. Held, it does not move at all:
   * same category, same list, and only the mark travels.
   *
   * It is dropped the moment the reader is not on a document, so the front page
   * is never left wearing the last section they were in.
   */
  const [lastSection, setLastSection] = useState<string | null>(null)

  /* Not yet known is not the same answer as none: a document still in flight is
     `null` here, while one that belongs to no section at all — a standalone
     wiki page — resolves with a category of null and puts the rail back at the
     front, where it belongs. */
  const resolved = here === null ? { categoryId: null } : within
  const slug =
    categorySlug(pathname) ??
    (resolved === null
      ? lastSection
      : ((browsable ?? []).find((category) => category.id === resolved.categoryId)?.slug ?? null))
  if (slug !== lastSection) setLastSection(slug)

  /*
   * The bottom of the tree is the only level whose contents are fetched, and
   * only the one the reader is standing on. A category with sub-categories
   * lists those and needs nothing else; asking every category in the institute
   * what it holds, to draw one list of one of them, is the cost this avoids.
   *
   * Keyed on the category rather than on the path, so moving between two guides
   * in a section does not ask again for the list they are both in.
   */
  const category = (browsable ?? []).find((candidate) => candidate.slug === slug) ?? null
  const hasChildren =
    category !== null && (browsable ?? []).some((child) => child.parentId === category.id)
  const bottom = category !== null && !hasChildren ? category.id : null

  const { data: contents } = useAsync(async () => {
    if (bottom === null) return null
    const [guides, pages] = await Promise.all([
      api.listGuides({ categoryId: bottom }),
      api.listPages({ categoryId: bottom }),
    ])
    return { guides, pages }
  }, [api, bottom])

  const { heading, headingTo, places, currentId } = railPlaces(
    browsable ?? [],
    slug,
    contents,
    here?.key ?? null,
  )

  if (places.length === 0) return null

  return (
    <>
      <hr className="rail__rule" />
      {/* The heading is the way back up out of the level below it: from a guide
          it is the only route to the section's own page that does not go
          through the front. */}
      <h2 className="rail__section">
        {headingTo === null ? heading : <Link to={headingTo}>{heading}</Link>}
      </h2>
      <div className="rail__places">
        {places.map((place) => (
          <Link
            key={place.id}
            className={`rail__item${place.id === currentId ? ' rail__item--on' : ''}`}
            to={place.to}
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

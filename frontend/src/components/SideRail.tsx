/**
 * The dark column down the left of every wide screen.
 *
 * It answers two questions, and it answers them in two labelled areas rather
 * than in one list, because they are not the same question and a reader
 * scanning for one should not have to read past the other.
 *
 * **Navigation** is the way in: the front page, and under it the sections
 * passed through to arrive where the reader is standing. It is a path, so it
 * grows a row at a time as they descend and each row is the way back to that
 * level.
 *
 * **Content** is what is here: the sections inside this one, or — at the bottom
 * of the tree — the guides and pages themselves. Standing at an instrument with
 * a procedure open, "which of the other confocal systems has a guide for this"
 * is one glance rather than two page loads.
 *
 * Splitting them is what let the heading become a label. It used to name the
 * level *and* be the only route back up to it, which meant the one word above
 * the list changed on every navigation and a reader could not learn it. Now the
 * route back up is the path, where a route back up belongs, and the two
 * headings are fixed.
 *
 * The wiki and tag indexes are in neither. Both list every page and every tag
 * in the institute regardless of where the reader is standing, which is the one
 * question the rail is not for — and neither is how ZMB navigates: a wiki page
 * is reached as part of the section that holds it, and a tag from the guide
 * wearing it. They keep their addresses, reached from the breadcrumb of the
 * page or tag a reader is already looking at.
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

import { useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import type { Category, GuideSummary, PageSummary } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { useBrowsableCategories } from '../hooks/useCategories'
import { ReticleMark } from './icons'

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

/** What the content area lists, and which of it is open. */
export interface Places {
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
 * The path from the front page down to where the reader is standing.
 *
 * Home is always its first row, because the front page is always somewhere to
 * go back to; the sections follow, outermost first, ending with the one the
 * reader is in. Reading a guide is standing in the category that holds it, so
 * a guide's path is its section's — the guide itself is marked in the content
 * area below and does not repeat here.
 *
 * A category outside `browsable` ends the walk rather than appearing in it: a
 * hidden holding category is not a place the reader can be sent, and a path
 * with a dead end in the middle of it is worse than a short one.
 */
export function railTrail(browsable: Category[], slug: string | null): RailPlace[] {
  const trail: RailPlace[] = []
  let at = slug === null ? undefined : browsable.find((c) => c.slug === slug)
  while (at) {
    trail.unshift(categoryPlace(at))
    const parentId: string | null = at.parentId
    at = parentId === null ? undefined : browsable.find((c) => c.id === parentId)
  }
  return [{ id: 'home', slug: '', name: 'Home', to: '/' }, ...trail]
}

/**
 * What the content area lists, given where the reader is.
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
 * An empty category, and a category whose documents are still on their way,
 * list nothing at all — the area is simply not drawn. This used to fall back to
 * the level above so that the column would not go blank, which was the right
 * answer when the column was the only thing saying where the reader was; the
 * path above says so now, and always. Listing the *siblings* of an empty
 * category under a heading reading "Content" would have been a third meaning
 * for one word, and a list that appears at the moment there is nothing to show.
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

  if (current) {
    const children = byOrder(browsable.filter((c) => c.parentId === current.id))
    if (children.length > 0) {
      return { places: children.map(categoryPlace), currentId: null }
    }

    const inside = contents === null ? [] : contentsPlaces(contents)
    const open =
      reading === null
        ? undefined
        : inside.find((place) => place.id === reading || place.slug === reading)
    return { places: inside, currentId: open?.id ?? null }
  }

  return {
    places: byOrder(browsable.filter((c) => c.parentId === null)).map(categoryPlace),
    currentId: null,
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
 * One labelled area: a rule, a heading, and the places under it.
 *
 * Both areas are built from this so that neither can drift into looking like
 * the more important one. `scrolls` is the single difference, and it is on the
 * content area alone: that list is as long as a section is, while the path is
 * as long as the tree is deep. A path that had scrolled out of reach would be a
 * way back out that the reader cannot get to.
 */
function RailGroup({
  heading,
  scrolls = false,
  children,
}: {
  heading: string
  scrolls?: boolean
  children: ReactNode
}) {
  return (
    <>
      <hr className="rail__rule" />
      <h2 className="rail__section">{heading}</h2>
      <div className={`rail__places rail__places--${scrolls ? 'content' : 'trail'}`}>
        {children}
      </div>
    </>
  )
}

/**
 * The two areas, drawn the same in the rail and in the phone drawer — they are
 * the same navigation, and a reader who learns it on a desktop should find it
 * in the same words in their hand.
 *
 * The content area is not shown while the categories are still coming: the rail
 * is furniture, and a column that flickers on every navigation is worse than
 * one that fills in a moment later. Whatever went wrong is reported by the
 * page. The path is drawn from the first render, because Home is in it whatever
 * the answer turns out to be.
 */
export function RailGroups() {
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
    /* Null, not an answer of "no category": this value survives into the first
       render after a navigation, and a leftover answer there is what tells the
       rail below that it need not hold anything. */
    if (!here) return null
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
   * Opening a guide from its category, or stepping from one procedure to the
   * next, re-fetches the document, and for that moment nothing in the path or
   * in hand says which category it belongs to. Without the held answer the
   * column emptied of its neighbours, showed the list of categories, and filled
   * back in — twice a click, on the one screen a reader spends real time on.
   * Held, it does not move at all: same section, same list, and only the mark
   * travels.
   *
   * It is dropped the moment the reader is not on a document, so the front page
   * is never left wearing the last section they were in.
   */
  const [lastSection, setLastSection] = useState<string | null>(null)

  /* Not yet known is not the same answer as none: a document still in flight
     leaves this null and the last section stands, while one that belongs to no
     section at all — a standalone wiki page — resolves with a category of null
     and puts the rail back at the front, where it belongs. */
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

  const { places, currentId } = railPlaces(browsable ?? [], slug, contents, here?.key ?? null)
  const trail = railTrail(browsable ?? [], slug)

  /* The path marks a step only when that step is the address in the bar. On a
     guide nothing in it is marked: the reader is *in* Confocal but they are
     *looking at* the guide, which is the row marked below, and two marks would
     make the column say the reader is in two places. */
  const openCategory = categorySlug(pathname)
  const isOpen = (place: RailPlace) =>
    place.to === '/' ? pathname === '/' : place.slug === openCategory

  return (
    <>
      <RailGroup heading="Navigation">
        {trail.map((place, depth) => (
          <Link
            key={place.id}
            className={`rail__item rail__item--step${isOpen(place) ? ' rail__item--on' : ''}`}
            /* The step's own depth, so the stylesheet owns how far in each one
               sits and a third level needs no code here. */
            style={{ '--depth': depth } as CSSProperties}
            to={place.to}
            aria-current={isOpen(place) ? 'page' : undefined}
          >
            {place.name}
          </Link>
        ))}
      </RailGroup>

      {places.length > 0 && (
        <RailGroup heading="Content" scrolls>
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
        </RailGroup>
      )}
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

      <RailGroups />

      <div className="rail__spacer" />
      {account}
    </nav>
  )
}

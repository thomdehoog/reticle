import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { ancestorsOf } from '../domain/category'
import type { Category } from '../domain/types'

interface CategoryCrumbsProps {
  categories: Category[]
  /** Where the thing being shown lives; null for a standalone wiki page. */
  categoryId: string | null
  /** The first crumb, when the trail does not start from the guides. */
  root?: ReactNode
  /** Further crumbs after the category — "History", "Editing" and the like. */
  children?: ReactNode
}

/** One further crumb, with its separator, for use as a child of `CategoryCrumbs`. */
export function Crumb({ children }: { children: ReactNode }) {
  return (
    <>
      <span className="breadcrumb__sep" aria-hidden="true">
        /
      </span>
      {children}
    </>
  )
}

/**
 * The trail from the front page down through a category and its parents.
 *
 * One component so that the reader, the editor and the history screens cannot
 * disagree about where a guide lives — the editor's trail used to stop at
 * "Editing", with no way back to the category the guide was filed in.
 */
export function CategoryCrumbs({ categories, categoryId, root, children }: CategoryCrumbsProps) {
  const category = categories.find((candidate) => candidate.id === categoryId)
  const trail = category ? [...ancestorsOf(categories, category), category] : []

  return (
    <nav className="breadcrumb" aria-label="Breadcrumb">
      {root ?? <Link to="/">Guides</Link>}
      {trail.map((entry) => (
        <Crumb key={entry.id}>
          <Link to="/c/$slug" params={{ slug: entry.slug }}>
            {entry.name}
          </Link>
        </Crumb>
      ))}
      {children}
    </nav>
  )
}

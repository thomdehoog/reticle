import { useSuspenseQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { PageRow } from '../components/GuideRow'
import { IconPlus } from '../components/icons'
import { NewPageDialog } from '../components/NewPageDialog'
import { EmptyState } from '../components/ui'
import { byOrder } from '../domain/category'
import type { PageSummary } from '../domain/types'
import { categoryQueries } from '../queries/categories'
import { pageQueries } from '../queries/pages'

/**
 * Every wiki page in one place.
 *
 * A page filed in a category is found through that category. A standalone
 * article has no such home — before this index existed, the only ways to one
 * were a link someone had written by hand, or search. Articles therefore come
 * first here; pages that belong to a category follow, grouped under it.
 */
export function WikiIndexPage() {
  const api = useApi()
  const { can } = useSession()
  const { data: pages } = useSuspenseQuery(pageQueries.list(api))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const [creating, setCreating] = useState(false)

  const categoryName = (page: PageSummary) =>
    categories.find((category) => category.id === page.categoryId)?.name

  /* Articles are what this index is for. Landing pages are listed too, since
     a wiki index that left pages out would be lying — but after the articles,
     and in the categories' own order, because each is really reached through
     its category. */
  const articles = pages.filter((page) => !page.isLanding)
  const position = new Map([...categories].sort(byOrder).map((category, index) => [category.id, index]))
  const landings = pages
    .filter((page) => page.isLanding)
    .sort((a, b) => (position.get(a.categoryId ?? '') ?? 0) - (position.get(b.categoryId ?? '') ?? 0))

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Wiki</h1>
          <p className="page-header__sub">
            Background, rules and reference material — everything that is not a step-by-step guide.
          </p>
        </div>
        {can('author') && (
          <div className="page-actions">
            <button className="button button--primary" type="button" onClick={() => setCreating(true)}>
              <IconPlus />
              New wiki page
            </button>
          </div>
        )}
      </div>

      {pages.length === 0 && (
        <EmptyState>
          <p>There are no wiki pages yet.</p>
          {can('author') && (
            <p className="empty-state__action">
              <button className="button" type="button" onClick={() => setCreating(true)}>
                Write the first page
              </button>
            </p>
          )}
        </EmptyState>
      )}

      {articles.length > 0 && (
        <section className="section">
          <h2 className="section__title">Articles</h2>
          <div className="card">
            {articles.map((page) => (
              <PageRow key={page.id} page={page} categoryName={categoryName(page)} />
            ))}
          </div>
        </section>
      )}

      {landings.length > 0 && (
        <section className="section">
          <h2 className="section__title">Category pages</h2>
          <div className="card">
            {landings.map((page) => (
              <PageRow key={page.id} page={page} categoryName={categoryName(page)} />
            ))}
          </div>
        </section>
      )}

      {creating && <NewPageDialog onClose={() => setCreating(false)} />}
    </>
  )
}

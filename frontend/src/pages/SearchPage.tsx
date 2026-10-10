import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { GuideRow, PageRow } from '../components/GuideRow'
import { EmptyState } from '../components/ui'
import { searchQueries } from '../queries/search'

const route = getRouteApi('/search')

/**
 * Search spans both content types.
 *
 * Splitting guides from wiki pages rather than interleaving them is deliberate:
 * someone looking for a procedure and someone looking for reference material
 * are asking different questions, and a merged relevance ranking would bury one
 * behind the other.
 */
export function SearchPage() {
  const { q: query } = route.useSearch()
  const api = useApi()
  const { data: results } = useSuspenseQuery(searchQueries.results(api, query))

  const guides = results.flatMap((result) => (result.kind === 'guide' ? [result.guide] : []))
  const pages = results.flatMap((result) => (result.kind === 'page' ? [result.page] : []))

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Search</h1>
          <p className="page-header__sub">
            {query === '' ? 'Type a search term above.' : `Results for “${query}”`}
          </p>
        </div>
      </div>

      {query !== '' && results.length === 0 && (
        <EmptyState>
          <p>Nothing matches “{query}”.</p>
          <p className="empty-state__action">
            Try an instrument name, or{' '}
            <Link to="/tags">browse the tags</Link>.
          </p>
        </EmptyState>
      )}

      {guides.length > 0 && (
        <section className="section">
          <h2 className="section__title">
            Guides <span className="result-count">{guides.length}</span>
          </h2>
          <div className="card">
            {guides.map((guide) => (
              <GuideRow key={guide.id} guide={guide} />
            ))}
          </div>
        </section>
      )}

      {pages.length > 0 && (
        <section className="section">
          <h2 className="section__title">
            Wiki pages <span className="result-count">{pages.length}</span>
          </h2>
          <div className="card">
            {pages.map((page) => (
              <PageRow key={page.id} page={page} />
            ))}
          </div>
        </section>
      )}
    </>
  )
}

import { Link, useSearchParams } from 'react-router-dom'

import { useApi } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import type { PageSummary } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

/** A wiki result. Labelled, because "guide" and "page" behave differently. */
function PageRow({ page }: { page: PageSummary }) {
  return (
    <Link className="guide-row" to={`/w/${page.slug}`}>
      <div className="guide-row__main">
        <div className="guide-row__title">{page.title}</div>
        {page.summary && <div className="guide-row__summary">{page.summary}</div>}
        <div className="guide-row__meta">
          <span className="result-kind">Wiki page</span>
          {page.isLanding && <span>Category landing page</span>}
        </div>
      </div>
      {page.status !== 'published' && <StatusBadge status={page.status} />}
    </Link>
  )
}

/**
 * Search spans both content types.
 *
 * Splitting guides from wiki pages rather than interleaving them is deliberate:
 * someone looking for a procedure and someone looking for reference material
 * are asking different questions, and a merged relevance ranking would bury one
 * behind the other.
 */
export function SearchPage() {
  const [params] = useSearchParams()
  const query = params.get('q') ?? ''
  const api = useApi()

  const { data, error, loading } = useAsync(
    () => (query === '' ? Promise.resolve([]) : api.search(query)),
    [api, query],
  )

  const results = data ?? []
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

      {loading && query !== '' && <Spinner />}
      <ErrorAlert error={error} />

      {!loading && !error && query !== '' && results.length === 0 && (
        <EmptyState>
          Nothing matches “{query}”. Try an instrument name, or browse by tag from any guide.
        </EmptyState>
      )}

      {guides.length > 0 && (
        <section style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>
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
        <section>
          <h2 style={{ marginBottom: '0.75rem' }}>
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

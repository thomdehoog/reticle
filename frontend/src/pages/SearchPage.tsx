/**
 * Search results, across guides and wiki pages together.
 *
 * Somebody looking for "immersion oil" does not know or care whether the answer
 * was written as a step-by-step guide or as a page of explanation, and a search
 * that covered only one would send them to the one place the answer is not.
 *
 * The two kinds are shown in separate blocks rather than interleaved. Someone
 * after a procedure and someone after reference material are asking different
 * questions, and a merged relevance ranking would bury one behind the other.
 */

import { useSearchParams } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { GuideCard, TileGrid, WikiCard } from '../components/BrowseCards'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

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
          <TileGrid>
            {guides.map((guide) => (
              <GuideCard key={guide.id} guide={guide} />
            ))}
          </TileGrid>
        </section>
      )}

      {pages.length > 0 && (
        <section>
          <h2 style={{ marginBottom: '0.75rem' }}>
            Wiki pages <span className="result-count">{pages.length}</span>
          </h2>
          <div className="card">
            {pages.map((page) => (
              <WikiCard key={page.id} page={page} />
            ))}
          </div>
        </section>
      )}
    </>
  )
}

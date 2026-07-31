import { useSearchParams } from 'react-router-dom'

import { useApi } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

export function SearchPage() {
  const [params] = useSearchParams()
  const query = params.get('q') ?? ''
  const api = useApi()

  const { data, error, loading } = useAsync(
    () => (query === '' ? Promise.resolve([]) : api.listGuides({ q: query })),
    [api, query],
  )

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

      {data && data.length === 0 && query !== '' && !loading && (
        <EmptyState>No guides match “{query}”.</EmptyState>
      )}

      {data && data.length > 0 && (
        <div className="card">
          {data.map((guide) => (
            <GuideRow key={guide.id} guide={guide} />
          ))}
        </div>
      )}
    </>
  )
}

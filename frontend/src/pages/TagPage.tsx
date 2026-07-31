import { Link, useParams } from 'react-router-dom'

import { useApi } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

/**
 * Every guide carrying a tag, wherever it lives.
 *
 * This is the listing the category tree cannot produce: a guide sits in one
 * category but is relevant to several instruments, and the tag is what gathers
 * it with its siblings.
 */
export function TagPage() {
  const { tag = '' } = useParams()
  const api = useApi()

  const { data, error, loading } = useAsync(
    () => api.listGuides({ tags: tag }),
    [api, tag],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />

  const guides = data ?? []

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep">/</span>
        <span>Tagged</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{tag}</h1>
          <p className="page-header__sub">
            {guides.length} {guides.length === 1 ? 'guide carries' : 'guides carry'} this tag.
          </p>
        </div>
      </div>

      {guides.length === 0 ? (
        <EmptyState>No published guides are tagged “{tag}”.</EmptyState>
      ) : (
        <div className="card">
          {guides.map((guide) => (
            <GuideRow key={guide.id} guide={guide} />
          ))}
        </div>
      )}
    </>
  )
}

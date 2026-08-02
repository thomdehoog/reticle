/**
 * Everything carrying one tag.
 */

import { Link, useParams } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { GuideCard, TileGrid } from '../components/BrowseCards'
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
        <Link to="/t">Tags</Link>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{tag}</h1>
          <p className="page-header__sub">
            {guides.length} {guides.length === 1 ? 'guide carries' : 'guides carry'} this tag.
          </p>
        </div>
      </div>

      {/* The listing is not restricted to published guides — an author sees
          their drafts here — so the empty state must not claim it was, or an
          author who has just tagged a draft is told it does not exist. */}
      {guides.length === 0 ? (
        <EmptyState>
          Nothing carries the tag “{tag}”. <Link to="/t">See which tags are in use.</Link>
        </EmptyState>
      ) : (
        <TileGrid>
          {guides.map((guide) => (
            <GuideCard key={guide.id} guide={guide} />
          ))}
        </TileGrid>
      )}
    </>
  )
}

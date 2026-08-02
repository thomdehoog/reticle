/**
 * Every tag, with how many guides carry it.
 *
 * Tags are the real index of this corpus - one guide about the LAS X software
 * belongs under ten different instruments, which is something categories alone
 * cannot express. This page is the way in to that.
 */

import { Link } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

/**
 * Every tag in use, with counts.
 *
 * Tags are the real index at ZMB — 137 of them across 257 guides — and until
 * now the only way to see one was to already be looking at a guide that carried
 * it. The counts come from the server against the same visibility rule as the
 * guide list, so no tag here leads to an empty page.
 */
export function TagIndexPage() {
  const api = useApi()
  const { data, error, loading } = useAsync(() => api.listTags(), [api])

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />

  const tags = data ?? []

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep">/</span>
        <span>Tags</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>Tags</h1>
          <p className="page-header__sub">
            One guide belongs to a single category but carries every tag it is relevant to, so this
            is usually the faster way in.
          </p>
        </div>
      </div>

      {tags.length === 0 ? (
        <EmptyState>No tags are in use yet.</EmptyState>
      ) : (
        <div className="tag-row tag-row--index">
          {tags.map((tag) => (
            <Link key={tag.id} className="tag tag--counted" to={`/t/${encodeURIComponent(tag.slug)}`}>
              {tag.name}
              <span className="tag__count">{tag.guideCount}</span>
            </Link>
          ))}
        </div>
      )}
    </>
  )
}

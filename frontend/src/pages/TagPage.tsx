/**
 * Every guide carrying one tag, wherever in the tree it lives.
 *
 * This is the listing the category tree cannot produce. A guide sits in exactly
 * one category, but a procedure for the LAS X software is relevant at ten
 * different instruments, and the tag is what gathers it with its siblings —
 * which is why tags, not categories, are how ZMB's corpus is actually
 * navigated. It is its own screen rather than part of the tag index because a
 * tag is a destination people link to and print from, so it needs a URL of its
 * own.
 */

import { Link, useParams } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { GuideCard, TileGrid } from '../components/BrowseCards'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { groupHeading } from '../domain/groups'
import { useAsync } from '../hooks/useAsync'

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
          {/* The same form the group heading that led here used, so arriving
              does not look like arriving somewhere else. */}
          <h1>{groupHeading(tag)}</h1>
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

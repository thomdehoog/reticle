import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { GuideRow } from '../components/GuideRow'
import { EmptyState } from '../components/ui'
import { guideQueries } from '../queries/guides'
import { tagQueries } from '../queries/tags'

const route = getRouteApi('/t/$tag')

/**
 * Every guide carrying a tag, wherever it lives.
 *
 * This is the listing the category tree cannot produce: a guide sits in one
 * category but is relevant to several instruments, and the tag is what gathers
 * it with its siblings.
 */
export function TagPage() {
  const { tag } = route.useParams()
  const api = useApi()
  const { data: guides } = useSuspenseQuery(guideQueries.list(api, { tags: tag }))
  const { data: tags } = useSuspenseQuery(tagQueries.list(api))

  /* The URL carries the slug; the heading shows the tag as it was first
     written ("LAS X", not "las-x") when the server knows it. A tag no visible
     guide carries is not listed, and falls back to the slug. */
  const name = tags.find((candidate) => candidate.slug === tag)?.name ?? tag

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep" aria-hidden="true">
          /
        </span>
        <Link to="/tags">Tags</Link>
        <span className="breadcrumb__sep" aria-hidden="true">
          /
        </span>
        <span>{name}</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{name}</h1>
          <p className="page-header__sub">
            {guides.length} {guides.length === 1 ? 'guide carries' : 'guides carry'} this tag.
          </p>
        </div>
        <div className="page-actions">
          <Link className="button" to="/tags">
            All tags
          </Link>
        </div>
      </div>

      {guides.length === 0 ? (
        <EmptyState>No published guides are tagged “{name}”.</EmptyState>
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

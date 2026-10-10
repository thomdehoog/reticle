import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { IconEdit } from '../components/icons'
import { LazyMarkdownBody } from '../components/LazyMarkdownBody'
import { StatusBadge } from '../components/ui'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { pageQueries } from '../queries/pages'

const route = getRouteApi('/w/$slug')

/** A wiki page: long-form guidance, with guide lists gathered by tag inside it. */
export function PageViewPage() {
  const { slug } = route.useParams()
  const api = useApi()
  const { can } = useSession()
  const { data: page } = useSuspenseQuery(pageQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))

  useRecordView(page.id, (id) => api.recordPageView(id))

  const category = categories.find((candidate) => candidate.id === page.categoryId)
  const otherContributors = page.contributors.filter((person) => person.id !== page.author.id)

  return (
    <article className="guide">
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {category && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to="/c/$slug" params={{ slug: category.slug }}>
              {category.name}
            </Link>
          </>
        )}
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{page.title}</h1>
          {page.summary && <p className="page-header__sub">{page.summary}</p>}
        </div>
        <div className="page-actions">
          {page.status !== 'published' && <StatusBadge status={page.status} />}
          {can('author') && (
            <Link className="button" to="/w/$id/edit" params={{ id: page.id }}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      {page.heroMediaId && (
        <img
          src={api.mediaUrl(page.heroMediaId)}
          alt=""
          style={{ display: 'block', maxWidth: '100%', marginBottom: '1.5rem' }}
        />
      )}

      <LazyMarkdownBody body={page.body} />

      {/* The same provenance a guide carries: who to ask, and how current it is. */}
      <p className="page-header__sub" style={{ marginTop: '2rem' }}>
        {page.author.displayName}
        {otherContributors.length > 0 &&
          `, with ${otherContributors.map((person) => person.displayName).join(', ')}`}
        {page.publishedAt &&
          ` · version ${page.version}, published ${new Date(page.publishedAt).toLocaleDateString()}`}
      </p>
    </article>
  )
}

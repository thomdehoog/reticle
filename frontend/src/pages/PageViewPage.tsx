import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryCrumbs } from '../components/CategoryCrumbs'
import { IconEdit, IconHistory } from '../components/icons'
import { PageBody } from '../components/PageBody'
import { DraftNotice, StatusBadge } from '../components/ui'
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

  return (
    <article className="guide">
      <CategoryCrumbs
        categories={categories}
        categoryId={page.categoryId}
        /* A standalone article hangs off the wiki index, not off a category. */
        root={page.categoryId === null ? <Link to="/wiki">Wiki</Link> : undefined}
      />

      <div className="page-header">
        <div className="page-header__text">
          <h1>{page.title}</h1>
          {page.summary && <p className="page-header__sub">{page.summary}</p>}
        </div>
        <div className="page-actions">
          {page.status !== 'published' && <StatusBadge status={page.status} />}
          {can('author') && (
            <Link className="button" to="/w/$slug/history" params={{ slug: page.slug }}>
              <IconHistory />
              History
            </Link>
          )}
          {can('author') && (
            <Link className="button" to="/w/$id/edit" params={{ id: page.id }}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      {page.status !== 'published' && <DraftNotice noun="page" />}

      <PageBody page={page} />
    </article>
  )
}

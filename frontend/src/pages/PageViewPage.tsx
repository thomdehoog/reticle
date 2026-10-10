import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryCrumbs } from '../components/CategoryCrumbs'
import { IconEdit, IconHistory } from '../components/icons'
import { PageBody } from '../components/PageBody'
import { DraftNotice, Spinner, StatusBadge } from '../components/ui'
import { PreviewBanner, UnpublishedChangesNotice } from '../components/UnpublishedChanges'
import { usePublishedView } from '../hooks/usePublishedView'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { pageQueries } from '../queries/pages'

const route = getRouteApi('/w/$slug')

/**
 * A wiki page: long-form guidance, with guide lists gathered by tag inside it.
 *
 * Like the guide reader, it shows everyone what readers see; an author with
 * unpublished changes is told so and can preview them.
 */
export function PageViewPage() {
  const { slug } = route.useParams()
  const { preview } = route.useSearch()
  const api = useApi()
  const { can } = useSession()
  const { data: given } = useSuspenseQuery(pageQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const view = usePublishedView(given, pageQueries.published(api, slug), preview === true)

  useRecordView(given.id, (id) => api.recordPageView(id))

  const page = view.shown
  if (!page) return <Spinner />

  return (
    <article className="guide">
      <CategoryCrumbs
        categories={categories}
        categoryId={page.categoryId}
        /* A standalone article hangs off the wiki index, not off a category. */
        root={page.categoryId === null ? <Link to="/wiki">Wiki</Link> : undefined}
      />

      {view.previewing && (
        <PreviewBanner noun="page" version={given.version}>
          <Link className="button button--sm" to="/w/$slug" params={{ slug: page.slug }}>
            Back to what readers see
          </Link>
          <Link className="button button--sm" to="/w/$id/edit" params={{ id: page.id }}>
            Edit
          </Link>
        </PreviewBanner>
      )}

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

      {view.behind && (
        <UnpublishedChangesNotice noun="page" version={page.version}>
          <Link
            className="button button--sm"
            to="/w/$slug"
            params={{ slug: page.slug }}
            search={{ preview: true }}
          >
            Preview changes
          </Link>
          <Link className="button button--sm" to="/w/$id/edit" params={{ id: page.id }}>
            Edit
          </Link>
        </UnpublishedChangesNotice>
      )}

      <PageBody page={page} />
    </article>
  )
}

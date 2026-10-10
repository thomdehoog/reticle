import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryCrumbs } from '../components/CategoryCrumbs'
import { GuideBody } from '../components/GuideBody'
import { IconDownload, IconEdit, IconHistory, IconPrint } from '../components/icons'
import { DraftNotice, StatusBadge } from '../components/ui'
import { formatDate } from '../domain/dates'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'

const route = getRouteApi('/g/$slug')

export function GuideViewPage() {
  const { slug } = route.useParams()
  const api = useApi()
  const { can } = useSession()
  const { data: guide } = useSuspenseQuery(guideQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))

  /* Reading is counted here and nowhere else, so opening a guide in the editor
     does not inflate its own figure. */
  useRecordView(guide.id, (id) => api.recordGuideView(id))

  return (
    <article className="guide">
      <CategoryCrumbs categories={categories} categoryId={guide.categoryId} />

      {/* Only ever seen on paper: a printout with no provenance is how somebody
          ends up following a superseded procedure taped to an instrument. */}
      <div className="print-only">
        Reticle · ZMB, University of Zurich — {guide.title}
        {guide.publishedAt &&
          ` · version ${guide.version}, published ${formatDate(guide.publishedAt)}`}
        {` · printed ${formatDate(new Date().toISOString())}`}
      </div>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{guide.title}</h1>
          {guide.summary && <p className="page-header__sub">{guide.summary}</p>}
        </div>
        <div className="page-actions">
          {guide.status !== 'published' && <StatusBadge status={guide.status} />}
          <button className="button" type="button" onClick={() => window.print()}>
            <IconPrint />
            Print
          </button>
          {/* A plain link: the browser fetches the file with the session
              cookie, and `download` keeps it from navigating away. */}
          <a className="button" href={api.guidePdfUrl(guide.slug)} download>
            <IconDownload />
            PDF
          </a>
          {can('author') && (
            <Link className="button" to="/g/$slug/history" params={{ slug: guide.slug }}>
              <IconHistory />
              History
            </Link>
          )}
          {can('author') && (
            <Link className="button" to="/g/$id/edit" params={{ id: guide.id }}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      {guide.status !== 'published' && <DraftNotice noun="guide" />}

      <GuideBody guide={guide} />
    </article>
  )
}

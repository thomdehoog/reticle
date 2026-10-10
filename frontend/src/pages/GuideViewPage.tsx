import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryCrumbs } from '../components/CategoryCrumbs'
import { GuideBody } from '../components/GuideBody'
import { IconDownload, IconEdit, IconHistory, IconPrint } from '../components/icons'
import { DraftNotice, Spinner, StatusBadge } from '../components/ui'
import { PreviewBanner, UnpublishedChangesNotice } from '../components/UnpublishedChanges'
import { formatDate } from '../domain/dates'
import type { Guide } from '../domain/types'
import { usePdfDownload } from '../hooks/usePdfDownload'
import { usePublishedView } from '../hooks/usePublishedView'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'

const route = getRouteApi('/g/$slug')

/**
 * A guide, as its readers have it.
 *
 * For a viewer that is the only version there is. An author who has edited a
 * published guide gets the published version here too — this is the screen a
 * link is sent to, and it should show what the person receiving the link will
 * see — with a note that newer work exists and a way to preview it.
 */
export function GuideViewPage() {
  const { slug } = route.useParams()
  const { preview } = route.useSearch()
  const api = useApi()
  const { data: given } = useSuspenseQuery(guideQueries.detail(api, slug))
  const view = usePublishedView(given, guideQueries.published(api, slug), preview === true)

  /* Reading is counted here and nowhere else, so opening a guide in the editor
     does not inflate its own figure. */
  useRecordView(given.id, (id) => api.recordGuideView(id))

  if (!view.shown) return <Spinner />
  return <GuideReader guide={view.shown} working={given} previewing={view.previewing} behind={view.behind} />
}

function GuideReader({
  guide,
  working,
  previewing,
  behind,
}: {
  guide: Guide
  /** The author's working copy; the same object as `guide` unless `behind`. */
  working: Guide
  previewing: boolean
  behind: boolean
}) {
  const api = useApi()
  const { can } = useSession()
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))

  /* The file should be the document on screen. For a published guide that is
     the published version, which the server renders once and then keeps. */
  const pdf = usePdfDownload(
    guide.slug,
    guide.status === 'published' && !previewing ? 'published' : undefined,
  )

  return (
    <article className="guide">
      <CategoryCrumbs categories={categories} categoryId={guide.categoryId} />

      {/* Only ever seen on paper: a printout with no provenance is how somebody
          ends up following a superseded procedure taped to an instrument. */}
      <div className="print-only">
        Reticle · ZMB, University of Zurich — {guide.title}
        {previewing
          ? ' · UNPUBLISHED PREVIEW, not the version readers have'
          : guide.publishedAt &&
            ` · version ${guide.version}, published ${formatDate(guide.publishedAt)}`}
        {` · printed ${formatDate(new Date().toISOString())}`}
      </div>

      {previewing && (
        <PreviewBanner noun="guide" version={working.version}>
          <Link className="button button--sm" to="/g/$slug" params={{ slug: guide.slug }}>
            Back to what readers see
          </Link>
          <Link className="button button--sm" to="/g/$id/edit" params={{ id: guide.id }}>
            Edit
          </Link>
        </PreviewBanner>
      )}

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
          <button className="button" type="button" onClick={pdf.start} disabled={pdf.busy}>
            <IconDownload />
            {pdf.busy ? 'Preparing PDF…' : 'PDF'}
          </button>
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

      {/* Always in the page, so that a message arriving in it is announced. */}
      <div role="status" aria-live="polite">
        {pdf.state.phase === 'waiting' && (
          <div className="alert alert--info">{pdf.state.message}</div>
        )}
        {pdf.state.phase === 'failed' && (
          <div className="alert alert--warning">{pdf.state.message}</div>
        )}
      </div>

      {guide.status !== 'published' && <DraftNotice noun="guide" />}

      {behind && (
        <UnpublishedChangesNotice noun="guide" version={guide.version}>
          <Link
            className="button button--sm"
            to="/g/$slug"
            params={{ slug: guide.slug }}
            search={{ preview: true }}
          >
            Preview changes
          </Link>
          <Link className="button button--sm" to="/g/$id/edit" params={{ id: guide.id }}>
            Edit
          </Link>
        </UnpublishedChangesNotice>
      )}

      <GuideBody guide={guide} />
    </article>
  )
}

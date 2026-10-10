import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { CategoryCrumbs, Crumb } from '../components/CategoryCrumbs'
import { GuideBody } from '../components/GuideBody'
import { RevisionBanner, RevisionList, newestFirst } from '../components/History'
import { NotFound } from '../components/RouteStates'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'

const historyRoute = getRouteApi('/g/$slug/history')
const revisionRoute = getRouteApi('/g/$slug/v/$version')

/** Every published version of a guide. Authors only; the route guards it. */
export function GuideHistoryPage() {
  const { slug } = historyRoute.useParams()
  const api = useApi()
  const { data: guide } = useSuspenseQuery(guideQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const { data: revisions } = useSuspenseQuery(guideQueries.revisions(api, guide.id))

  return (
    <div className="guide">
      <CategoryCrumbs categories={categories} categoryId={guide.categoryId}>
        <Crumb>
          <Link to="/g/$slug" params={{ slug: guide.slug }}>
            {guide.title || 'Untitled guide'}
          </Link>
        </Crumb>
        <Crumb>
          <span>History</span>
        </Crumb>
      </CategoryCrumbs>

      <div className="page-header">
        <div className="page-header__text">
          <h1>History</h1>
          <p className="page-header__sub">
            Published versions of “{guide.title || 'Untitled guide'}”. Open one to read it as it
            was.
          </p>
        </div>
        <div className="page-actions">
          <Link className="button" to="/g/$slug" params={{ slug: guide.slug }}>
            Back to the guide
          </Link>
        </div>
      </div>

      <RevisionList
        noun="guide"
        revisions={revisions}
        renderLink={(revision, children) => (
          <Link
            className="revision-list__row"
            to="/g/$slug/v/$version"
            params={{ slug: guide.slug, version: String(revision.version) }}
          >
            {children}
          </Link>
        )}
      />
    </div>
  )
}

/** One past version, read-only, drawn by the same component as the live guide. */
export function GuideRevisionPage() {
  const { slug, version } = revisionRoute.useParams()
  const api = useApi()
  const { data: guide } = useSuspenseQuery(guideQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const { data: revisions } = useSuspenseQuery(guideQueries.revisions(api, guide.id))
  const { data: snapshot } = useSuspenseQuery(
    guideQueries.revision(api, guide.id, Number(version)),
  )

  const revision = revisions.find((candidate) => candidate.version === Number(version))
  if (!revision) return <NotFound />

  return (
    <article className="guide">
      <CategoryCrumbs categories={categories} categoryId={guide.categoryId}>
        <Crumb>
          <Link to="/g/$slug" params={{ slug: guide.slug }}>
            {guide.title || 'Untitled guide'}
          </Link>
        </Crumb>
        <Crumb>
          <Link to="/g/$slug/history" params={{ slug: guide.slug }}>
            History
          </Link>
        </Crumb>
        <Crumb>
          <span>Version {revision.version}</span>
        </Crumb>
      </CategoryCrumbs>

      <RevisionBanner
        revision={revision}
        superseded={newestFirst(revisions)[0]?.version !== revision.version}
      >
        <Link className="button button--sm" to="/g/$slug/history" params={{ slug: guide.slug }}>
          All versions
        </Link>
        <Link className="button button--sm" to="/g/$slug" params={{ slug: guide.slug }}>
          Current guide
        </Link>
      </RevisionBanner>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{snapshot.title}</h1>
          {snapshot.summary && <p className="page-header__sub">{snapshot.summary}</p>}
        </div>
      </div>

      <GuideBody guide={snapshot} />
    </article>
  )
}

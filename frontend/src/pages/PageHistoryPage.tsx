import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { CategoryCrumbs, Crumb } from '../components/CategoryCrumbs'
import { RevisionBanner, RevisionList, newestFirst } from '../components/History'
import { PageBody } from '../components/PageBody'
import { NotFound } from '../components/RouteStates'
import type { Page } from '../domain/types'
import { categoryQueries } from '../queries/categories'
import { pageQueries } from '../queries/pages'

const historyRoute = getRouteApi('/w/$slug/history')
const revisionRoute = getRouteApi('/w/$slug/v/$version')

function wikiRoot(page: Page) {
  return page.categoryId === null ? <Link to="/wiki">Wiki</Link> : undefined
}

/** The wiki counterpart of `GuideHistoryPage`. */
export function PageHistoryPage() {
  const { slug } = historyRoute.useParams()
  const api = useApi()
  const { data: page } = useSuspenseQuery(pageQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const { data: revisions } = useSuspenseQuery(pageQueries.revisions(api, page.id))

  return (
    <div className="guide">
      <CategoryCrumbs categories={categories} categoryId={page.categoryId} root={wikiRoot(page)}>
        <Crumb>
          <Link to="/w/$slug" params={{ slug: page.slug }}>
            {page.title || 'Untitled page'}
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
            Published versions of “{page.title || 'Untitled page'}”. Open one to read it as it was.
          </p>
        </div>
        <div className="page-actions">
          <Link className="button" to="/w/$slug" params={{ slug: page.slug }}>
            Back to the page
          </Link>
        </div>
      </div>

      <RevisionList
        noun="page"
        revisions={revisions}
        renderLink={(revision, children) => (
          <Link
            className="revision-list__row"
            to="/w/$slug/v/$version"
            params={{ slug: page.slug, version: String(revision.version) }}
          >
            {children}
          </Link>
        )}
      />
    </div>
  )
}

export function PageRevisionPage() {
  const { slug, version } = revisionRoute.useParams()
  const api = useApi()
  const { data: page } = useSuspenseQuery(pageQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const { data: revisions } = useSuspenseQuery(pageQueries.revisions(api, page.id))
  const { data: snapshot } = useSuspenseQuery(pageQueries.revision(api, page.id, Number(version)))

  const revision = revisions.find((candidate) => candidate.version === Number(version))
  if (!revision) return <NotFound />

  return (
    <article className="guide">
      <CategoryCrumbs categories={categories} categoryId={page.categoryId} root={wikiRoot(page)}>
        <Crumb>
          <Link to="/w/$slug" params={{ slug: page.slug }}>
            {page.title || 'Untitled page'}
          </Link>
        </Crumb>
        <Crumb>
          <Link to="/w/$slug/history" params={{ slug: page.slug }}>
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
        <Link className="button button--sm" to="/w/$slug/history" params={{ slug: page.slug }}>
          All versions
        </Link>
        <Link className="button button--sm" to="/w/$slug" params={{ slug: page.slug }}>
          Current page
        </Link>
      </RevisionBanner>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{snapshot.title}</h1>
          {snapshot.summary && <p className="page-header__sub">{snapshot.summary}</p>}
        </div>
      </div>

      <PageBody page={snapshot} />
    </article>
  )
}

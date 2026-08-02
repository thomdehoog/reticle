import { Link } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { TileGrid, WikiCard } from '../components/BrowseCards'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import type { PageSummary } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { useCategories } from '../hooks/useCategories'

/**
 * Every wiki page in one list.
 *
 * Without it, a page was reachable only from search or from a link somebody
 * remembered to write, so a page that nobody linked to was effectively deleted
 * the day it was published. Landing pages are marked because they belong to a
 * category and are usually read from there instead.
 */
export function WikiIndexPage() {
  const api = useApi()
  const { can } = useAuth()
  const { data: categories } = useCategories()
  const { data, error, loading } = useAsync(() => api.listPages(), [api])

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />

  const pages = data ?? []
  const categoryName = (page: PageSummary) =>
    categories?.find((category) => category.id === page.categoryId)?.name ?? null

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep">/</span>
        <span>Wiki</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>Wiki</h1>
          <p className="page-header__sub">
            Reference material that is not a step-by-step procedure — background, policy, and the
            category pages that gather guides by tag.
          </p>
        </div>
      </div>

      {pages.length === 0 ? (
        <EmptyState>
          No wiki pages yet.
          {can('author') && ' Use “New page” above to write the first one.'}
        </EmptyState>
      ) : (
        <TileGrid>
          {pages.map((page) => (
            <WikiCard key={page.id} page={page} context={categoryName(page)} />
          ))}
        </TileGrid>
      )}
    </>
  )
}

import { Link, useParams } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { IconEdit } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

/** A wiki page: long-form guidance, with guide lists gathered by tag inside it. */
export function PageViewPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const page = await api.getPage(slug)
      const categories = await api.listCategories()
      return { page, categories }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That page does not exist.</EmptyState>

  const { page, categories } = data
  const category = categories.find((candidate) => candidate.id === page.categoryId)

  return (
    <article className="guide">
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {category && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to={`/c/${category.slug}`}>{category.name}</Link>
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
            <Link className="button" to={`/w/${page.id}/edit`}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      <MarkdownBody body={page.body} />
    </article>
  )
}

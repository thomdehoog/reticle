import { Link, useParams } from 'react-router-dom'

import { useApi } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

export function CategoryPage() {
  const { slug = '' } = useParams()
  const api = useApi()

  const { data, error, loading } = useAsync(
    async () => {
      const categories = await api.listCategories()
      const category = categories.find((candidate) => candidate.slug === slug) ?? null
      const guides = category ? await api.listGuides({ categoryId: category.id }) : []
      return { categories, category, guides }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data?.category) return <EmptyState>That category does not exist.</EmptyState>

  const { category, categories, guides } = data
  const children = categories
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const parent = category.parentId
    ? categories.find((candidate) => candidate.id === category.parentId)
    : undefined

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {parent && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to={`/c/${parent.slug}`}>{parent.name}</Link>
          </>
        )}
        <span className="breadcrumb__sep">/</span>
        <span>{category.name}</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{category.name}</h1>
          {category.description && <p className="page-header__sub">{category.description}</p>}
        </div>
      </div>

      {children.length > 0 && (
        <div className="grid" style={{ marginBottom: '2rem' }}>
          {children.map((child) => (
            <Link key={child.id} to={`/c/${child.slug}`} className="category-card">
              <span className="category-card__name">{child.name}</span>
              {child.description && <span className="category-card__desc">{child.description}</span>}
            </Link>
          ))}
        </div>
      )}

      {guides.length === 0 ? (
        <EmptyState>No guides in this category yet.</EmptyState>
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

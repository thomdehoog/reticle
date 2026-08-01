import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { IconEdit, IconPlus } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { browsableCategories } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

/**
 * A category: its landing page if somebody has written one, and its guides.
 *
 * The landing page is the point of this screen at ZMB. Their category pages are
 * prose with tag-gathered guide lists embedded in them — "Confocal systems",
 * then the guides carrying that tag — and a bare alphabetical list of every
 * guide in the category is exactly what that arrangement exists to avoid. The
 * plain list stays as the fallback, because a category nobody has written a
 * page for yet must still show its contents.
 */
export function CategoryPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)

  const { data, error, loading } = useAsync(
    async () => {
      const categories = await api.listCategories()
      const category = categories.find((candidate) => candidate.slug === slug) ?? null
      if (!category) return { categories, category, guides: [], landing: null }

      const [guides, landing] = await Promise.all([
        api.listGuides({ categoryId: category.id }),
        api.getCategoryLandingPage(category.id),
      ])
      return { categories, category, guides, landing }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data?.category) return <EmptyState>That category does not exist.</EmptyState>

  const { category, categories, guides, landing } = data
  const children = browsableCategories(categories)
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const parent = category.parentId
    ? categories.find((candidate) => candidate.id === category.parentId)
    : undefined

  async function startLandingPage() {
    if (!data?.category) return
    setCreating(true)
    setCreateError(null)
    try {
      const page = await api.createPage({
        title: data.category.name,
        categoryId: data.category.id,
        isLanding: true,
      })
      navigate(`/w/${page.id}/edit`)
    } catch (cause) {
      setCreateError(cause)
      setCreating(false)
    }
  }

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
        {can('author') && (
          <div className="page-actions">
            {landing && landing.status !== 'published' && <StatusBadge status={landing.status} />}
            {landing ? (
              <Link className="button" to={`/w/${landing.id}/edit`}>
                <IconEdit />
                Edit landing page
              </Link>
            ) : (
              <button
                className="button"
                type="button"
                disabled={creating}
                onClick={() => void startLandingPage()}
              >
                <IconPlus />
                {creating ? 'Creating…' : 'Write a landing page'}
              </button>
            )}
          </div>
        )}
      </div>

      <ErrorAlert error={createError} />

      {landing && <MarkdownBody body={landing.body} />}

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

      {/* With a landing page in front of it, the full list is a reference rather
          than the navigation, so it is labelled and does not claim the page. */}
      {landing && guides.length > 0 && (
        <h2 style={{ margin: '2rem 0 0.75rem' }}>Everything in {category.name}</h2>
      )}

      {guides.length === 0 ? (
        !landing && <EmptyState>No guides in this category yet.</EmptyState>
      ) : (
        <div className="card category-guides">
          {guides.map((guide) => (
            <GuideRow key={guide.id} guide={guide} />
          ))}
        </div>
      )}
    </>
  )
}

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { CategoryTile, GuideCard, TileGrid, WikiCard } from '../components/BrowseCards'
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
      if (!category) return { categories, category, guides: [], landing: null, pages: [] }

      const [guides, landing, pages] = await Promise.all([
        api.listGuides({ categoryId: category.id }),
        api.getCategoryLandingPage(category.id),
        api.listPages({ categoryId: category.id }),
      ])
      return { categories, category, guides, landing, pages }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data?.category) return <EmptyState>That category does not exist.</EmptyState>

  const { category, categories, guides, landing, pages } = data
  const articles = pages.filter((page) => !page.isLanding)
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

      {landing && <MarkdownBody body={landing.body} wide />}

      {children.length > 0 && (
        <section className="section">
          <h2 className="section__title">Sections</h2>
          <TileGrid>
            {children.map((child) => (
              <CategoryTile
                key={child.id}
                category={child}
                guideCount={guides.filter((guide) => guide.categoryId === child.id).length}
              />
            ))}
          </TileGrid>
        </section>
      )}

      {/* Wiki pages other than the landing one: at ZMB these are the written
          material a section carries beside its procedures, and they are reached
          from here rather than only from search. */}
      {articles.length > 0 && (
        <section className="section">
          <h2 className="section__title">Wiki pages</h2>
          <TileGrid>
            {articles.map((page) => (
              <WikiCard key={page.id} page={page} />
            ))}
          </TileGrid>
        </section>
      )}

      {guides.length === 0 ? (
        !landing && <EmptyState>No guides in this section yet.</EmptyState>
      ) : (
        <section className="section category-guides">
          {/* With a landing page in front of it, the full list is a reference
              rather than the navigation, so it says so and does not claim the
              page. */}
          <h2 className="section__title">
            {landing ? `Everything in ${category.name}` : 'Guides'}
          </h2>
          <TileGrid>
            {guides.map((guide) => (
              <GuideCard key={guide.id} guide={guide} />
            ))}
          </TileGrid>
        </section>
      )}
    </>
  )
}

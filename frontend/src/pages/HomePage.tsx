import { Link } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { buildCategoryTree } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

/**
 * The landing page: the category tree, plus an author's own unfinished work.
 *
 * Surfacing drafts here is deliberate — a half-written guide that nobody can
 * see from the front page is a half-written guide that never gets finished.
 */
export function HomePage() {
  const api = useApi()
  const { user, can } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const [categories, guides] = await Promise.all([api.listCategories(), api.listGuides()])
      return { categories, guides }
    },
    [api],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return null

  const roots = buildCategoryTree(data.categories)

  const publishedPerCategory = new Map<string, number>()
  for (const guide of data.guides) {
    if (guide.status !== 'published') continue
    publishedPerCategory.set(guide.categoryId, (publishedPerCategory.get(guide.categoryId) ?? 0) + 1)
  }

  const countIncludingChildren = (categoryId: string): number => {
    const node = data.categories.filter((c) => c.parentId === categoryId)
    return (
      (publishedPerCategory.get(categoryId) ?? 0) +
      node.reduce((total, child) => total + countIncludingChildren(child.id), 0)
    )
  }

  const myDrafts = data.guides.filter(
    (guide) => guide.status !== 'published' && guide.author.id === user?.id,
  )

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Guides</h1>
          <p className="page-header__sub">
            Standard procedures for the Center for Microscopy and Image Analysis
          </p>
        </div>
      </div>

      {roots.length === 0 ? (
        <EmptyState>No categories yet.</EmptyState>
      ) : (
        <div className="grid">
          {roots.map((category) => {
            const count = countIncludingChildren(category.id)
            return (
              <Link key={category.id} to={`/c/${category.slug}`} className="category-card">
                <span className="category-card__name">{category.name}</span>
                {category.description && (
                  <span className="category-card__desc">{category.description}</span>
                )}
                <span className="category-card__count">
                  {count} {count === 1 ? 'guide' : 'guides'}
                </span>
              </Link>
            )
          })}
        </div>
      )}

      {can('author') && myDrafts.length > 0 && (
        <section style={{ marginTop: '2.5rem' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>Your unpublished guides</h2>
          <div className="card">
            {myDrafts.map((guide) => (
              <GuideRow key={guide.id} guide={guide} to={`/g/${guide.id}/edit`} />
            ))}
          </div>
        </section>
      )}
    </>
  )
}

import { Link } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { GuideRow } from '../components/GuideRow'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { browsableCategories, buildCategoryTree } from '../hooks/useCategories'
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
  const authorId = can('author') ? (user?.id ?? null) : null

  /**
   * Two narrow listings rather than one broad one. This screen used to pull
   * every guide in the institute — drafts, other people's in-review work, the
   * lot — to derive a count per card and to find the reader's own drafts. A
   * viewer therefore downloaded the entire editorial pipeline to be shown eight
   * numbers. The counts now come from published guides only, which is what the
   * cards claim to count, and the drafts query is scoped to one author and only
   * runs for someone who can write.
   */
  const { data, error, loading } = useAsync(
    async () => {
      const [categories, published, mine] = await Promise.all([
        api.listCategories(),
        api.listGuides({ status: 'published' }),
        authorId === null ? Promise.resolve([]) : api.listGuides({ authorId }),
      ])
      return { categories, published, mine }
    },
    [api, authorId],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return null

  const roots = buildCategoryTree(browsableCategories(data.categories))

  const publishedPerCategory = new Map<string, number>()
  for (const guide of data.published) {
    publishedPerCategory.set(guide.categoryId, (publishedPerCategory.get(guide.categoryId) ?? 0) + 1)
  }

  /**
   * A parent card counts what is underneath it, hidden children included: those
   * guides really are reachable from here through the page's own links, and a
   * "0 guides" card over a category full of them reads as a broken section.
   */
  const countIncludingChildren = (categoryId: string): number => {
    const children = data.categories.filter((c) => c.parentId === categoryId)
    return (
      (publishedPerCategory.get(categoryId) ?? 0) +
      children.reduce((total, child) => total + countIncludingChildren(child.id), 0)
    )
  }

  const myDrafts = data.mine.filter((guide) => guide.status !== 'published')

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

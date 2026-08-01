import { useApi, useAuth } from '../auth/AuthContext'
import { CategoryTile, GuideCard, TileGrid } from '../components/BrowseCards'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { browsableCategories, buildCategoryTree } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

/**
 * The front door: the sections, as pictures.
 *
 * Somebody arriving here is looking for an instrument or a procedure they
 * already have in mind, and they recognise it faster than they can read a list
 * of titles — so this is a wall of tiles rather than a table of contents, and
 * the words on each one are held to the name and a count. The description of a
 * section belongs on the section, where somebody has decided to read.
 *
 * Surfacing an author's drafts here is deliberate: a half-written guide that
 * nobody can see from the front page is a half-written guide that never gets
 * finished.
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
        <TileGrid>
          {roots.map((category) => (
            <CategoryTile
              key={category.id}
              category={category}
              guideCount={countIncludingChildren(category.id)}
              childCount={
                browsableCategories(data.categories).filter((c) => c.parentId === category.id).length
              }
            />
          ))}
        </TileGrid>
      )}

      {can('author') && myDrafts.length > 0 && (
        <section className="section">
          <h2 className="section__title">Your unpublished guides</h2>
          <TileGrid>
            {myDrafts.map((guide) => (
              <GuideCard key={guide.id} guide={guide} to={`/g/${guide.id}/edit`} />
            ))}
          </TileGrid>
        </section>
      )}
    </>
  )
}

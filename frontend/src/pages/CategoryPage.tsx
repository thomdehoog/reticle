/**
 * One category, opened up.
 *
 * A category shows one thing, and which thing depends on where it sits in the
 * tree. With sub-categories under it, it shows those and the quick links, and
 * nothing else: the guides belong to the level below, and listing them here as
 * well is the same procedures twice, once under a heading nobody has chosen
 * yet. With nothing under it — a leaf, whether that is a sub-category or a
 * top-level category that never needed dividing — it is the bottom of the tree,
 * so it shows the guides.
 *
 * The landing page is the point of the leaf screen at ZMB. Their category pages
 * are prose with tag-gathered guide lists embedded in them — "Confocal
 * systems", then the guides carrying that tag — and a bare alphabetical list of
 * every guide in the category is exactly what that arrangement exists to avoid.
 * The plain list stays as the fallback, because a category nobody has written a
 * page for yet must still show its contents.
 */

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { CategoryTile, GuideRow, GuideRows, TileGrid, WikiCard } from '../components/BrowseCards'
import { IconEdit, IconPlus } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { QuickLinks } from '../components/QuickLinks'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { browsableCategories } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

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
  const isLeaf = children.length === 0

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
      <div className="page-header">
        <div className="page-header__text">
          <h1>{category.name}</h1>
        </div>
      </div>

      <ErrorAlert error={createError} />

      {/* No heading over them: a row of pictures directly under a section's own
          name is not something a reader needs told is a list of sections. */}
      {!isLeaf && (
        <>
          <TileGrid>
            {children.map((child) => (
              <CategoryTile key={child.id} category={child} />
            ))}
          </TileGrid>
          <QuickLinks />
        </>
      )}

      {/* A landing page lists its guides itself, grouped under the instrument
          they belong to. Repeating all of them underneath it as one flat run is
          the same guides a second time, which is what the landing page was
          written to replace. Without one, this list is the section. */}
      {isLeaf && landing && <MarkdownBody body={landing.body} wide />}

      {isLeaf && !landing && guides.length > 0 && (
        <section className="section">
          <GuideRows>
            {guides.map((guide) => (
              <GuideRow key={guide.id} guide={guide} />
            ))}
          </GuideRows>
        </section>
      )}

      {isLeaf && !landing && guides.length === 0 && (
        <EmptyState>No guides in this section yet.</EmptyState>
      )}

      {/* Wiki pages other than the landing one: at ZMB these are the written
          material a section carries beside its procedures, and they are reached
          from here rather than only from search. The heading stays because the
          cards no longer carry the words "wiki page" themselves. */}
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

      {/* Writing the section's front page is an authoring job, and it sat at the
          top of a screen whose readers are almost never authors. It belongs
          after the thing it would change. */}
      {can('author') && (
        <div className="page-actions page-actions--footer">
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
    </>
  )
}

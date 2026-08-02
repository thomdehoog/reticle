/**
 * One category, opened up.
 *
 * Shows what is inside a category: any sub-categories, the wiki page that
 * introduces it if there is one, and the guides it holds - as pictures rather
 * than a list of titles, because people recognise the instrument they used far
 * faster than they recall what the procedure was called.
 *
 * The landing page is the point of this screen at ZMB. Their category pages are
 * prose with tag-gathered guide lists embedded in them — "Confocal systems",
 * then the guides carrying that tag — and a bare alphabetical list of every
 * guide in the category is exactly what that arrangement exists to avoid. The
 * plain list stays as the fallback, because a category nobody has written a
 * page for yet must still show its contents.
 */

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { CategoryTile, GuideRow, GuideRows, TileGrid, WikiCard } from '../components/BrowseCards'
import { IconEdit, IconPlus } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { browsableCategories, countGuidesByCategory } from '../hooks/useCategories'
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
      if (!category)
        return { categories, category, guides: [], published: [], landing: null, pages: [] }

      /* `published` is every published guide in the institute, which is what
         the sub-category counts are counted from: a listing scoped to this
         category holds none of a child's guides, so counting children against
         it returned nought for every one of them. */
      const [guides, published, landing, pages] = await Promise.all([
        api.listGuides({ categoryId: category.id }),
        api.listGuides({ status: 'published' }),
        api.getCategoryLandingPage(category.id),
        api.listPages({ categoryId: category.id }),
      ])
      return { categories, category, guides, published, landing, pages }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data?.category) return <EmptyState>That category does not exist.</EmptyState>

  const { category, categories, guides, published, landing, pages } = data
  const guideCount = countGuidesByCategory(categories, published)
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
      </div>

      <ErrorAlert error={createError} />

      {/* Sub-sections first: they are how somebody gets to the instrument they
          came for, and underneath the guide lists they were the last thing on
          the page. No heading — a row of pictures directly under a section's
          name is not something a reader needs told is a list of sections. */}
      {children.length > 0 && (
        <TileGrid>
          {children.map((child) => (
            <CategoryTile key={child.id} category={child} guideCount={guideCount(child.id)} />
          ))}
        </TileGrid>
      )}

      {landing && <MarkdownBody body={landing.body} wide />}

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

      {/* A landing page lists its guides itself, grouped under the instrument
          they belong to. Repeating all of them underneath it as one flat run is
          the same guides a second time, which is what the landing page was
          written to replace. Without one, this list is the section. */}
      {!landing && guides.length > 0 && (
        <section className="section">
          <GuideRows>
            {guides.map((guide) => (
              <GuideRow key={guide.id} guide={guide} />
            ))}
          </GuideRows>
        </section>
      )}

      {!landing && guides.length === 0 && children.length === 0 && (
        <EmptyState>No guides in this section yet.</EmptyState>
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

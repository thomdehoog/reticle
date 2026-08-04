/**
 * One category, opened up.
 *
 * Which guides a category shows depends on where it sits in the tree. With
 * sub-categories under it, it shows those and the quick links and no guides at
 * all: the guides belong to the level below, and listing them here as well is
 * the same procedures twice, once under a heading nobody has chosen yet. With
 * nothing under it — a leaf, whether that is a sub-category or a top-level
 * category that never needed dividing — it is the bottom of the tree, so it
 * shows the guides.
 *
 * The landing page is shown at both levels, because what is duplicated is the
 * lists and not the writing around them. At ZMB a category page is prose with
 * tag-gathered guide lists embedded in it — "Confocal systems", then the guides
 * carrying that tag — and a bare alphabetical list of every guide in the
 * category is exactly what that arrangement exists to avoid. On a parent the
 * lists come out and the prose stays; on a leaf the page is the whole screen.
 * The plain list stays as the fallback, because a category nobody has written a
 * page for yet must still show its contents.
 */

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { Banner } from '../components/Banner'
import { CategoryTile, GuideRow, GuideRows, TileGrid, WikiCard } from '../components/BrowseCards'
import { IconEdit, IconPlus } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { QuickLinks } from '../components/QuickLinks'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { mediaUrl } from '../domain/types'
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
      if (!category) {
        return {
          categories,
          category,
          guides: [],
          landing: null,
          pages: [],
          publishedGuides: [],
          publishedPages: [],
        }
      }

      const [guides, landing, pages, publishedGuides, publishedPages] = await Promise.all([
        api.listGuides({ categoryId: category.id }),
        api.getCategoryLandingPage(category.id),
        api.listPages({ categoryId: category.id }),
        api.listGuides({ status: 'published' }),
        api.listPages({ status: 'published' }),
      ])
      return { categories, category, guides, landing, pages, publishedGuides, publishedPages }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data?.category) return <EmptyState>That category does not exist.</EmptyState>

  const { category, categories, guides, landing, pages } = data
  const articles = pages.filter((page) => !page.isLanding)
  const children = browsableCategories(categories, data.publishedGuides, data.publishedPages)
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
      {/* The section's own words and picture, from whichever of the two places
          holds them. A category carries a `description` and a picture an
          administrator sets, and its landing page carries a `summary` and a
          hero — and at ZMB the second is where both actually are, because the
          migration reads the vendor's category wiki into the landing page.
          Preferring the administrator's means setting either in the admin
          screen does something; falling through to the page's means every
          imported section arrives with the paragraph and the photograph ZMB
          already had, rather than a title floating on drawn artwork.

          Both fall through the same way on purpose: splitting them — words from
          one place, picture from the other — is how a section ends up with a
          photograph of one instrument over a sentence about another. */}
      <Banner
        title={category.name}
        intro={category.description || landing?.summary}
        src={category.imageUrl ?? (landing?.heroMediaId ? mediaUrl(landing.heroMediaId) : null)}
      />

      <ErrorAlert error={createError} />

      {/* The page's own words come first, above the sections, because they are
          what the reader has to know before opening one of them: at ZMB, that
          you need an introduction on a system before you can book it. Below a
          wall of tiles, on a phone, that sentence is under the fold.

          On a section with sub-sections the guide lists inside the page are
          suppressed, headings and all — the guides belong to the level below,
          and listing them here as well is the same procedures twice. The prose
          around them is not duplicated anywhere, which is why the page is
          rendered rather than skipped. */}
      {landing && <MarkdownBody body={landing.body} wide hideGuideLists={!isLeaf} />}

      {/* No heading over them: a row of pictures under a section's own name is
          not something a reader needs told is a list of sections. */}
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

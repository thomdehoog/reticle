/**
 * One section, opened up.
 *
 * A section shows exactly one kind of thing, and which kind is decided by where
 * it sits in the tree rather than by what somebody wrote on it:
 *
 * - with sub-sections under it, the sub-sections, as pictures;
 * - with none, its guides, under the tags that group them.
 *
 * That is the whole page. It used to be five things at once — a banner, the
 * landing page's prose, tiles, quick links, a plain list of guides as a
 * fallback, and a separate row of wiki cards — and no two sections showed the
 * same combination, because which of them appeared depended on whether anyone
 * had got round to writing a page for that section. A reader could not learn
 * the shape of a section page because there wasn't one.
 *
 * What this buys, beyond a page a reader can learn, is a content management
 * system with nothing in it to manage. **Nobody writes a section page.** An
 * author tags a guide and it appears under that tag, in the section it belongs
 * to. There is no page to draft, publish, version or forget to update, and no
 * embedded-list syntax to learn — the arrangement is a consequence of the
 * guides rather than a second thing to keep in step with them.
 *
 * The landing pages are still there, and still hold what the migration brought:
 * their words are what the banner reads, and the page itself keeps its address.
 * It is simply not this screen any more.
 */

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { Banner } from '../components/Banner'
import { CategoryTile, GuideRow, GuideRows, TileGrid } from '../components/BrowseCards'
import { IconEdit, IconPlus } from '../components/icons'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { groupGuides } from '../domain/groups'
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

  const { category, categories, guides, landing } = data
  const children = browsableCategories(categories, data.publishedGuides, data.publishedPages)
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const isLeaf = children.length === 0
  const grouped = groupGuides(guides)

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

      {/* No heading over them: a row of pictures under a section's own name is
          not something a reader needs told is a list of sections. */}
      {!isLeaf && (
        <TileGrid>
          {children.map((child) => (
            <CategoryTile key={child.id} category={child} />
          ))}
        </TileGrid>
      )}

      {/* The bottom of the tree: the procedures, under the tags that group
          them. A guide with several tags appears under each — that is what lets
          one LAS X guide sit under every instrument it applies to, and it is
          the arrangement the corpus was written for rather than an accident of
          the grouping. */}
      {isLeaf && (
        <>
          {grouped.loose.length > 0 && (
            <section className="section">
              <GuideRows>
                {grouped.loose.map((guide) => (
                  <GuideRow key={guide.id} guide={guide} />
                ))}
              </GuideRows>
            </section>
          )}

          {grouped.groups.map((group) => (
            <section className="section" key={group.tag}>
              <h2 className="section__title">
                <Link to={`/t/${encodeURIComponent(group.tag)}`}>{group.tag}</Link>
              </h2>
              <GuideRows>
                {group.guides.map((guide) => (
                  <GuideRow key={`${group.tag}-${guide.id}`} guide={guide} />
                ))}
              </GuideRows>
            </section>
          ))}

          {guides.length === 0 && <EmptyState>No guides in this section yet.</EmptyState>}
        </>
      )}

      {/* The landing page is no longer this screen, but it still exists and
          still holds what the migration brought. This is the only route to it,
          so it stays: content that is kept and unreachable is worse than
          content that is deleted on purpose. Author-only, so no reader meets
          it. */}
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

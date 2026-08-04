/**
 * One section, opened up.
 *
 * What a section shows is decided by where it sits in the tree rather than by
 * what somebody wrote on it:
 *
 * - with sub-sections under it, the sub-sections, as pictures;
 * - with none, it is the bottom of the tree, and it lists what it holds.
 *
 * The list at the bottom is in two parts, wikis and then guides, and each part
 * appears only if it has anything in it. The wikis are a plain list: they are
 * the written material a section carries beside its procedures, there are few
 * of them, and grouping half a dozen articles is furniture around nothing. The
 * guides are grouped by tag, because that is how a facility's procedures
 * actually divide — `Talos`, then start-up, then acquisition, then shutdown —
 * and because a guide belongs under every instrument it applies to.
 *
 * Reading before doing is why the wikis come first: they answer "which of these
 * do I want", and the guides answer "how".
 *
 * That is the whole page. It used to be five things at once — a banner, the
 * landing page's prose, tiles, quick links, a plain list of guides as a
 * fallback, and a separate grid of wiki cards — and no two sections showed the
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
import { CategoryTile, GuideRow, GuideRows, PageRow, TileGrid } from '../components/BrowseCards'
import { IconEdit, IconPlus } from '../components/icons'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { GROUP_ANCHORS, groupAnchor, groupGuides, groupHeading } from '../domain/groups'
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
  const children = browsableCategories(categories, data.publishedGuides, data.publishedPages)
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const isLeaf = children.length === 0
  const grouped = groupGuides(guides)
  /* The landing page is the section's front, not something inside it — its
     words are already in the banner above, so listing it here would be the
     page a reader is standing on offered as somewhere to go. */
  const articles = pages.filter((page) => !page.isLanding)

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
      {/* The section's own words, from whichever of the two places holds them.
          A category carries a `description` an administrator types and its
          landing page carries a `summary` — and at ZMB the second is where the
          words are, because the migration reads the vendor's category
          description into it. Preferring the typed one keeps the admin screen
          meaningful; falling through means every imported section arrives with
          the paragraph ZMB already wrote.

          The picture needs no fallback here: `imageUrl` already carries it,
          because a section's photograph reaches a reader through the tile and
          the search card as well as this banner, and a rule kept on one screen
          is a rule the other two do not have. */}
      <Banner title={category.name} intro={category.description || landing?.summary} src={category.imageUrl} />

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

      {isLeaf && (
        <>
          {/* Guides nobody has tagged yet, above the groups and under no
              heading — a section part-tagged is an ordinary state, not one to
              invent a name for. */}
          {grouped.loose.length > 0 && (
            <section className="section">
              <GuideRows>
                {grouped.loose.map((guide) => (
                  <GuideRow key={guide.id} guide={guide} />
                ))}
              </GuideRows>
            </section>
          )}

          {/* The articles, as a group like any other: same heading, same link,
              same rows. It was briefly special — a heading that did not link,
              on the reasoning that `/w` is the whole institute's index rather
              than this section's articles. That reasoning made it the one group
              on the page that behaved differently, which is a worse thing for a
              reader to learn than a link whose destination is broader than they
              expected. Every group heading goes somewhere; so does this one. */}
          {articles.length > 0 && (
            <section className="section" id={GROUP_ANCHORS.wikis}>
              <h3 className="section__title">
                <Link to="/w">Wikis</Link>
              </h3>
              <GuideRows>
                {articles.map((page) => (
                  <PageRow key={page.id} page={page} />
                ))}
              </GuideRows>
            </section>
          )}

          {/* The groups, under the tags that make them — `Talos`, then start-up,
              acquisition, shutdown. A guide with several tags appears under
              each, which is what lets one LAS X guide sit under every
              instrument it applies to; that is the arrangement the corpus was
              written for rather than an accident of the grouping. */}
          {grouped.groups.map((group) => (
            <section className="section" key={group.tag} id={groupAnchor(group.tag)}>
              <h3 className="section__title">
                <Link to={`/t/${encodeURIComponent(group.tag)}`}>
                  {groupHeading(group.tag)}
                </Link>
              </h3>
              <GuideRows>
                {group.guides.map((guide) => (
                  <GuideRow key={`${group.tag}-${guide.id}`} guide={guide} />
                ))}
              </GuideRows>
            </section>
          ))}

          {guides.length === 0 && articles.length === 0 && (
            <EmptyState>Nothing in this section yet.</EmptyState>
          )}
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

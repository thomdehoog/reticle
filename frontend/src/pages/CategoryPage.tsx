/**
 * One section, opened up.
 *
 * What a section shows is decided by where it sits in the tree rather than by
 * what somebody wrote on it:
 *
 * - with sub-sections under it, the sub-sections, as pictures;
 * - with none, it is the bottom of the tree, and it lists what it holds.
 *
 * The list at the bottom is groups, and a group is rows pointing at an
 * endpoint — a guide or a wiki, and a reader has no reason to care which. They
 * are grouped by tag, because that is how a facility's material actually
 * divides — `Talos`, then start-up, then acquisition, then shutdown — and
 * because a guide belongs under every instrument it applies to.
 *
 * The wikis were one lump of their own at the top until a page could carry a
 * tag, which was not a decision about how to arrange them so much as the only
 * thing possible at the time. The article about the Nikon belongs beside the
 * procedures for it, and reading-before-doing survives inside each group, where
 * the wikis come first.
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
import { Link, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { Banner } from '../components/Banner'
import { SectionGrid } from '../components/SectionGrid'
import { SectionGroups } from '../components/SectionGroups'
import { IconEdit, IconPlus } from '../components/icons'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { groupDocuments, type Grouped } from '../domain/groups'
import { browsableCategories, isEmptyToReaders } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

export function CategoryPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can } = useAuth()
  /**
   * Groups made before they hold anything. A group is a tag worn by documents
   * and the server deliberately refuses a heading nothing is under — so a
   * group made here lives on screen only, until the first document created
   * inside it (or dragged into it) makes it real. Reloading recomputes the
   * real groups; whichever of these has become one drops out of the list.
   */
  const [pendingGroups, setPendingGroups] = useState<string[]>([])
  /** The group just made, so its name opens ready to be typed over. */
  const [justMade, setJustMade] = useState<string | null>(null)

  const { data, error, loading, reload } = useAsync(
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
  const children = browsableCategories(categories, data.publishedGuides, data.publishedPages, {
    keepEmpty: can('admin'),
  })
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const isLeaf = children.length === 0
  /* Nothing under it at all — no sections, no guides, no articles. The one
     state where an administrator is shown the tile that makes a section from
     inside a section, because it is the only thing this screen can offer. */
  const isBare = isLeaf && guides.length === 0 && pages.filter((page) => !page.isLanding).length === 0
  /* The landing page is the section's front, not something inside it — its
     words are already in the banner above, so listing it here would be the
     page a reader is standing on offered as somewhere to go. */
  const articles = pages.filter((page) => !page.isLanding)
  const grouped = groupDocuments(guides, articles, category.tagOrder)
  /* The made-but-still-empty groups, drawn after the real ones. One that has
     since gained a document arrives from the grouping itself and drops out
     of the pending list rather than appearing twice. */
  const stillPending = pendingGroups.filter(
    (tag) => !grouped.groups.some((group) => group.tag === tag),
  )
  const shownGrouped: Grouped = {
    ...grouped,
    groups: [...grouped.groups, ...stillPending.map((tag) => ({ tag, items: [] }))],
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
      <Banner
        title={category.name}
        intro={category.description || landing?.summary}
        src={category.imageUrl}
        /* Edit, and only edit, and only at the top of the tree. An
           administrator who has opened a section to read it is exactly the one
           who wants to change its words, so that belongs here — but a
           sub-section's banner stays clean: its words and picture are managed
           from the level above, where it is one tile of several. Deleting is
           done there too, where the thing being destroyed is visibly one of
           many and still there afterwards. */
        actions={
          can('admin') && category.parentId === null ? (
            <Link
              className="banner__action"
              to={`/categories/${category.id}/edit`}
              aria-label={`Edit ${category.name}`}
            >
              <IconEdit size={15} />
              Edit
            </Link>
          ) : null
        }
      />

      {/* The making, in a quiet bar under the banner. One button, one job,
          no dialog: the group simply appears, name selected and ready to be
          typed over — the documents are added inside it, which is what its
          own two buttons and the drag are for. Always present for an author
          on a section that lists documents, so an empty section greets them
          with the way out of the emptiness. */}
      {can('author') && isLeaf && (
        <div className="section-bar">
          <button
            type="button"
            className="button button--sm"
            onClick={() => {
              /* Slug-shaped from birth: a tag is a slug and the server
                 refuses any other shape, placeholder or not. */
              const taken = new Set([...grouped.groups.map((group) => group.tag), ...pendingGroups])
              let name = 'new-group'
              for (let n = 2; taken.has(name); n += 1) name = `new-group-${n}`
              setPendingGroups((current) => [...current, name])
              setJustMade(name)
            }}
          >
            <IconPlus size={15} />
            Add group
          </button>
        </div>
      )}

      {/* No heading over them: a row of pictures under a section's own name is
          not something a reader needs told is a list of sections.

          An administrator also gets the grid — for the tile that makes one — on
          a section holding nothing at all, where it is the only thing to do
          about an empty screen. Not on a section that is full of guides: each
          level of this tree shows one kind of thing, and a lone dashed tile
          above a page of procedures says sections are what this screen is for
          when they are not. Splitting a full section is the categories screen's
          job, which is where the whole tree is visible at once. */}
      {(!isLeaf || (can('admin') && isBare && category.parentId === null)) && (
        <SectionGrid
          categories={children}
          parentId={category.id}
          emptyIds={
            new Set(
              children
                .filter((child) =>
                  isEmptyToReaders(child, categories, data.publishedGuides, data.publishedPages),
                )
                .map((child) => child.id),
            )
          }
          /* Only a top-level section may be given sub-sections. The tree is two
             deep — a section holds sub-sections, a sub-section holds the guides
             and the wikis — and the server refuses a third level, so the tile
             that would ask for one is not drawn inside a sub-section. */
          canAdd={category.parentId === null}
          onChanged={reload}
        />
      )}

      {isLeaf && (
        <>
          {/* The groups, under the tags that make them — `Talos`, then start-up,
              acquisition, shutdown. A document with several tags appears under
              each, which is what lets one LAS X guide sit under every
              instrument it applies to; that is the arrangement the corpus was
              written for rather than an accident of the grouping.

              Which group a row is in is dragged rather than written, and the
              component that draws them owns that, because the preview during a
              drag is a different arrangement of the same data and this screen
              has no business holding two. */}
          <SectionGroups
            grouped={shownGrouped}
            categoryId={category.id}
            placedTags={category.tagOrder}
            justMade={justMade}
            onPendingRenamed={(from, to) =>
              setPendingGroups((current) => current.map((tag) => (tag === from ? to : tag)))
            }
            onChanged={reload}
          />

          {guides.length === 0 && articles.length === 0 && stillPending.length === 0 && (
            <EmptyState>
              Nothing in this section yet.
              {can('author') && ' Use “Add group” above to start filling it.'}
            </EmptyState>
          )}
        </>
      )}

      {/* "Edit landing page" used to sit here, and it was the only route to the
          document holding a section's words and picture. The section form is
          that route now, and it reaches the same two fields under the names a
          reader would use for them — so the button is gone rather than left as
          a second way to edit one thing. Nothing was deleted with it: the
          landing pages are where they were, and their longer `body` still
          belongs to them. */}

    </>
  )
}

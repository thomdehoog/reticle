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
import { GuideRow, GuideRows, PageRow } from '../components/BrowseCards'
import { SectionGrid } from '../components/SectionGrid'
import { IconEdit, IconTrash } from '../components/icons'
import { EmptyState, ErrorAlert, Modal, Spinner } from '../components/ui'
import { GROUP_ANCHORS, groupAnchor, groupGuides, groupHeading } from '../domain/groups'
import { browsableCategories } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

export function CategoryPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { can } = useAuth()
  const [deleting, setDeleting] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [password, setPassword] = useState('')
  const [createError, setCreateError] = useState<unknown>(null)

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
  const children = browsableCategories(categories, data.publishedGuides, data.publishedPages)
    .filter((candidate) => candidate.parentId === category.id)
    .sort((a, b) => a.orderIndex - b.orderIndex)
  const isLeaf = children.length === 0
  const grouped = groupGuides(guides)
  /* Nothing under it at all — no sections, no guides, no articles. The one
     state where an administrator is shown the tile that makes a section from
     inside a section, because it is the only thing this screen can offer. */
  const isBare = isLeaf && guides.length === 0 && pages.filter((page) => !page.isLanding).length === 0
  /* The landing page is the section's front, not something inside it — its
     words are already in the banner above, so listing it here would be the
     page a reader is standing on offered as somewhere to go. */
  const articles = pages.filter((page) => !page.isLanding)

  /* Deleting from the banner leaves the reader on a page that is gone, so it
     ends at the front rather than reloading into a 404. The server is what
     refuses a section that still holds anything; this only reports it. */
  async function removeSection() {
    if (!data?.category) return
    setRemoving(true)
    setCreateError(null)
    try {
      await api.deleteCategory(data.category.id, password)
      navigate('/')
    } catch (cause) {
      setCreateError(cause)
      setRemoving(false)
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
      <Banner
        title={category.name}
        intro={category.description || landing?.summary}
        src={category.imageUrl}
        /* Edit and delete sit on the banner as well as on the tile, because the
           tile is where a section is noticed and this is where it is read: an
           administrator who has opened a section to check its words is exactly
           the one who wants to change them, and sending them back to the grid
           to do it is a journey with nothing in it. */
        actions={
          can('admin') ? (
            <>
              <Link
                className="banner__action"
                to={`/categories/${category.id}/edit`}
                aria-label={`Edit ${category.name}`}
              >
                <IconEdit size={15} />
                Edit
              </Link>
              <button
                className="banner__action banner__action--danger"
                type="button"
                aria-label={`Delete ${category.name}`}
                onClick={() => setDeleting(true)}
              >
                <IconTrash size={15} />
                Delete
              </button>
            </>
          ) : null
        }
      />

      <ErrorAlert error={createError} />

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

      {/* "Edit landing page" used to sit here, and it was the only route to the
          document holding a section's words and picture. The section form is
          that route now, and it reaches the same two fields under the names a
          reader would use for them — so the button is gone rather than left as
          a second way to edit one thing. Nothing was deleted with it: the
          landing pages are where they were, and their longer `body` still
          belongs to them. */}

      {deleting && (
        <Modal
          title={`Delete ${category.name}?`}
          onClose={() => {
            setDeleting(false)
            setPassword('')
          }}
        >
          <ErrorAlert error={createError} />
          <p>
            <strong>Everything inside it goes as well</strong> — its sub-sections, and every guide and
            wiki page filed in any of them. They are deleted, not archived: this is the one place
            in Reticle where content does not come back.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void removeSection()
            }}
          >
            <div className="field">
              <label className="field__label" htmlFor="delete-section-password">
                Your password
              </label>
              <input
                id="delete-section-password"
                className="input"
                type="password"
                /* Every layer here exists because the one above it is ignored.
                   "off" is ignored by browsers on password fields; "new-password"
                   tells them this is not the saved credential, which Chrome and
                   Firefox honour. The three data attributes are 1Password,
                   LastPass and Bitwarden, which read their own and not the
                   standard one. And "readOnly" until the field is touched is what
                   catches the rest: a manager fills on load, and there is nothing
                   fillable on load. It clears on focus, so typing is unaffected.

                   No autoFocus, deliberately — focusing it on open would hand a
                   manager the moment it is waiting for. */
                autoComplete="new-password"
                data-1p-ignore
                data-lpignore="true"
                data-bwignore
                readOnly
                onFocus={(event) => {
                  event.currentTarget.readOnly = false
                }}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="page-actions">
              <button
                className="button button--danger"
                type="submit"
                disabled={removing || password === ''}
              >
                {removing ? 'Deleting…' : 'Delete section'}
              </button>
              <button
                className="button"
                type="button"
                onClick={() => {
                  setDeleting(false)
                  setPassword('')
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}

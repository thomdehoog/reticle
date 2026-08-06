/**
 * The front page: the sections, as pictures.
 *
 * The first screen after signing in. Somebody arriving here is looking for an
 * instrument or a procedure they already have in mind, and they recognise it
 * faster than they can read a list of titles — so this is a wall of tiles
 * rather than a table of contents, and the words on each one are the name and
 * nothing else. Under them are the quick links: the few procedures people
 * arrive asking for that no category name would lead them to.
 *
 * Surfacing an author's own drafts here is deliberate: a half-written guide
 * nobody can see from the front page is a half-written guide that never gets
 * finished. It sits last, because it is about the person rather than about the
 * material, and only an author has it at all.
 */

import { Link } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { Banner } from '../components/Banner'
import { IconEdit } from '../components/icons'
import { GuideCard, TileGrid } from '../components/BrowseCards'
import { QuickLinks } from '../components/QuickLinks'
import { SectionGrid } from '../components/SectionGrid'
import { EmptyState, ErrorAlert, Spinner } from '../components/ui'
import { browsableCategories, buildCategoryTree } from '../hooks/useCategories'
import { useAsync } from '../hooks/useAsync'

export function HomePage() {
  const api = useApi()
  const { user, can, organisation } = useAuth()
  const authorId = can('author') ? (user?.id ?? null) : null

  /**
   * Narrow listings rather than one broad one. The published ones are what says
   * whether a tile leads anywhere, and the drafts query is scoped to one author
   * and only runs for somebody who can write: one listing of every guide in the
   * institute would send a viewer the whole editorial pipeline — drafts and
   * other people's in-review work included — for a screen that shows neither.
   */
  const { data, error, loading, reload } = useAsync(
    async () => {
      const [categories, publishedGuides, publishedPages, mine] = await Promise.all([
        api.listCategories(),
        api.listGuides({ status: 'published' }),
        api.listPages({ status: 'published' }),
        authorId === null ? Promise.resolve([]) : api.listGuides({ authorId }),
      ])
      return { categories, publishedGuides, publishedPages, mine }
    },
    [api, authorId],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return null

  const roots = buildCategoryTree(
    browsableCategories(data.categories, data.publishedGuides, data.publishedPages),
  )
  const myDrafts = data.mine.filter((guide) => guide.status !== 'published')

  return (
    <>
      <Banner
        variant="facility"
        title={organisation?.name ?? 'Guides'}
        intro={organisation?.tagline}
        src={organisation?.heroImageUrl}
        /* Edit only. A section can be deleted because it is something the
           facility holds; the facility is the thing itself, and a button that
           removed the front page's name would have nothing to leave behind. */
        actions={
          can('admin') ? (
            <Link className="banner__action" to="/facility/edit" aria-label="Edit the front page">
              <IconEdit size={15} />
              Edit
            </Link>
          ) : null
        }
      />

      {/* An administrator is never shown "no categories yet" — the grid draws
          the tile that makes one, which is the same control they would reach
          for with thirty sections on screen. A reader still gets the sentence:
          for them there is nothing to do about it. */}
      {roots.length === 0 && !can('admin') ? (
        <EmptyState>No categories yet.</EmptyState>
      ) : (
        <SectionGrid categories={roots} onChanged={reload} />
      )}

      <QuickLinks />

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

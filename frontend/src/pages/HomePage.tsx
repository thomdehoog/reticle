import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryDialog } from '../components/CategoryDialog'
import { GuideRow, PageRow } from '../components/GuideRow'
import { IconPlus } from '../components/icons'
import { NewPageDialog } from '../components/NewPageDialog'
import { EmptyState } from '../components/ui'
import { buildBrowsableTree, byOrder, subtreeIds } from '../domain/category'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'
import { pageQueries } from '../queries/pages'

/**
 * The landing page: the category tree, the wiki, plus an author's own
 * unfinished work.
 *
 * Surfacing drafts here is deliberate — a half-written guide that nobody can
 * see from the front page is a half-written guide that never gets finished.
 */
export function HomePage() {
  const api = useApi()
  const { user, can } = useSession()
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))
  const { data: guides } = useSuspenseQuery(guideQueries.list(api))
  const { data: pages } = useSuspenseQuery(pageQueries.list(api))

  const [dialog, setDialog] = useState<'page' | 'category' | null>(null)

  const roots = buildBrowsableTree(categories)
  const hidden = categories.filter((category) => category.isHidden).sort(byOrder)

  const publishedPerCategory = new Map<string, number>()
  for (const guide of guides) {
    if (guide.status !== 'published') continue
    publishedPerCategory.set(guide.categoryId, (publishedPerCategory.get(guide.categoryId) ?? 0) + 1)
  }

  /* A landing page is reached through its category, so listing it again here
     would only be a second door to the same room. */
  const articles = pages.filter((page) => !page.isLanding)

  const myDrafts = guides.filter(
    (guide) => guide.status !== 'published' && guide.author.id === user?.id,
  )

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Guides</h1>
          <p className="page-header__sub">
            Standard procedures for the Center for Microscopy and Image Analysis
          </p>
        </div>
        {can('author') && (
          <div className="page-actions">
            <button className="button" type="button" onClick={() => setDialog('page')}>
              <IconPlus />
              New wiki page
            </button>
            {can('admin') && (
              <button className="button" type="button" onClick={() => setDialog('category')}>
                <IconPlus />
                New category
              </button>
            )}
          </div>
        )}
      </div>

      {roots.length === 0 ? (
        <EmptyState>No categories yet.</EmptyState>
      ) : (
        <div className="grid">
          {roots.map((category) => {
            const count = subtreeIds(category).reduce(
              (total, id) => total + (publishedPerCategory.get(id) ?? 0),
              0,
            )
            return (
              <Link
                key={category.id}
                to="/c/$slug"
                params={{ slug: category.slug }}
                className="category-card"
              >
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

      {articles.length > 0 && (
        <section style={{ marginTop: '2.5rem' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>Wiki pages</h2>
          <div className="card">
            {articles.map((page) => (
              <PageRow key={page.id} page={page} />
            ))}
          </div>
        </section>
      )}

      {can('author') && myDrafts.length > 0 && (
        <section style={{ marginTop: '2.5rem' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>Your unpublished guides</h2>
          <div className="card">
            {myDrafts.map((guide) => (
              <GuideRow key={guide.id} guide={guide} edit />
            ))}
          </div>
        </section>
      )}

      {/* Readers reach these guides through tags and never need the category
          itself. The people who file guides into one do. */}
      {can('author') && hidden.length > 0 && (
        <section style={{ marginTop: '2.5rem' }}>
          <h2 style={{ marginBottom: '0.25rem' }}>Hidden categories</h2>
          <p className="page-header__sub" style={{ marginBottom: '0.75rem' }}>
            Holding categories for guides that are found through tags. Readers do not see this list.
          </p>
          <div className="tag-row">
            {hidden.map((category) => (
              <Link
                key={category.id}
                className="tag"
                to="/c/$slug"
                params={{ slug: category.slug }}
              >
                {category.name}
              </Link>
            ))}
          </div>
        </section>
      )}

      {dialog === 'page' && <NewPageDialog onClose={() => setDialog(null)} />}
      {dialog === 'category' && (
        <CategoryDialog categories={categories} onClose={() => setDialog(null)} />
      )}
    </>
  )
}

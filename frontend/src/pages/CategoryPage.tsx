import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'
import { useState } from 'react'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryCrumbs, Crumb } from '../components/CategoryCrumbs'
import { CategoryDialog } from '../components/CategoryDialog'
import { GuideRow, PageRow } from '../components/GuideRow'
import { IconEdit, IconPlus } from '../components/icons'
import { LazyMarkdownBody } from '../components/LazyMarkdownBody'
import { NewPageDialog } from '../components/NewPageDialog'
import { NotFound } from '../components/RouteStates'
import { EmptyState, StatusBadge } from '../components/ui'
import { UnpublishedChangesNotice } from '../components/UnpublishedChanges'
import { browsableChildren } from '../domain/category'
import type { Category, Page } from '../domain/types'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'
import { pageQueries } from '../queries/pages'

const route = getRouteApi('/c/$slug')

/**
 * A category, resolved by the slug in the URL.
 *
 * The lookup runs over the full category list, hidden ones included: hiding a
 * category takes it out of the browsable tree, not off the map.
 */
export function CategoryPage() {
  const { slug } = route.useParams()
  const api = useApi()
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))

  const category = categories.find((candidate) => candidate.slug === slug)
  /* The loader has already answered "not found" for a slug that never existed;
     this covers one that stops existing while the page is open. */
  if (!category) return <NotFound />

  return <CategoryContent key={category.id} category={category} categories={categories} />
}

/** The landing page's text, counted as a read of that page. */
function LandingBody({ page }: { page: Page }) {
  const api = useApi()
  useRecordView(page.id, (id) => api.recordPageView(id))
  return <LazyMarkdownBody body={page.body} />
}

function CategoryContent({ category, categories }: { category: Category; categories: Category[] }) {
  const api = useApi()
  const { can } = useSession()
  const { data: guides } = useSuspenseQuery(guideQueries.list(api, { categoryId: category.id }))
  const { data: pages } = useSuspenseQuery(pageQueries.list(api, { categoryId: category.id }))
  /* What readers have as the landing page, and what this person is given by
     default. For a viewer the two are one request and one answer. For an
     author the second is the working copy, which is only what to show when
     nothing is published here yet — a landing page still being written. */
  const author = can('author')
  const { data: given } = useSuspenseQuery(pageQueries.landing(api, category.id))
  const { data: published } = useSuspenseQuery(
    pageQueries.landing(api, category.id, author ? 'published' : undefined),
  )
  const landing = published ?? given
  /* Shown to its author but not to readers: a draft, or a published page whose
     move to this category has been saved and not yet published. */
  const unseenByReaders = author && landing !== null && published === null

  const [dialog, setDialog] = useState<'landing' | 'category' | null>(null)

  const children = browsableChildren(categories, category.id)
  const articles = pages.filter((page) => !page.isLanding)
  const empty = guides.length === 0 && articles.length === 0 && children.length === 0 && !landing

  return (
    <>
      <CategoryCrumbs categories={categories} categoryId={category.parentId}>
        <Crumb>
          <span>{category.name}</span>
        </Crumb>
      </CategoryCrumbs>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{category.name}</h1>
          {category.description && <p className="page-header__sub">{category.description}</p>}
        </div>
        {can('author') && (
          <div className="page-actions">
            {landing && landing.status !== 'published' && <StatusBadge status={landing.status} />}
            {landing && (
              <Link className="button" to="/w/$id/edit" params={{ id: landing.id }}>
                <IconEdit />
                Edit landing page
              </Link>
            )}
            {can('admin') && (
              <button className="button" type="button" onClick={() => setDialog('category')}>
                Edit category
              </button>
            )}
          </div>
        )}
      </div>

      {landing && unseenByReaders && (
        <div className="alert alert--info" role="note">
          <strong>
            {landing.status === 'published'
              ? 'The landing page below is not published here yet.'
              : 'The landing page below is a draft.'}
          </strong>{' '}
          Readers see this category without it until it is published.
        </div>
      )}

      {landing && landing.hasUnpublishedChanges && !unseenByReaders && (
        <UnpublishedChangesNotice noun="landing page" version={landing.version}>
          <Link
            className="button button--sm"
            to="/w/$slug"
            params={{ slug: landing.slug }}
            search={{ preview: true }}
          >
            Preview changes
          </Link>
          <Link className="button button--sm" to="/w/$id/edit" params={{ id: landing.id }}>
            Edit
          </Link>
        </UnpublishedChangesNotice>
      )}

      {landing && (
        <div className="section">
          <LandingBody page={landing} />
        </div>
      )}

      {/* A category without a landing page is a bare list. Saying so, with the
          way to fix it, is how the lists turn into pages over time — but only
          to the people who can write one. */}
      {!landing && can('author') && (
        <div className="empty-state empty-state--compact section">
          <p>
            <strong>This category has no landing page yet.</strong> A landing page introduces the
            category and can gather guides from anywhere by tag.
          </p>
          <p className="empty-state__action">
            <button className="button" type="button" onClick={() => setDialog('landing')}>
              <IconPlus />
              Write this page
            </button>
          </p>
        </div>
      )}

      {children.length > 0 && (
        <section className="section">
          {(landing || guides.length > 0 || articles.length > 0) && (
            <h2 className="section__title">In this category</h2>
          )}
          <div className="grid">
            {children.map((child) => (
              <Link
                key={child.id}
                to="/c/$slug"
                params={{ slug: child.slug }}
                className="category-card"
              >
                <span className="category-card__name">{child.name}</span>
                {child.description && (
                  <span className="category-card__desc">{child.description}</span>
                )}
              </Link>
            ))}
          </div>
        </section>
      )}

      {articles.length > 0 && (
        <section className="section">
          <h2 className="section__title">Wiki pages</h2>
          <div className="card">
            {articles.map((page) => (
              <PageRow key={page.id} page={page} />
            ))}
          </div>
        </section>
      )}

      {guides.length > 0 && (
        <section className="section">
          {/* Only needs saying when something else on the page could be
              mistaken for it: a landing page usually embeds guide lists of
              its own, gathered by tag from other categories. */}
          {(landing || articles.length > 0 || children.length > 0) && (
            <h2 className="section__title">Guides in this category</h2>
          )}
          <div className="card">
            {guides.map((guide) => (
              <GuideRow key={guide.id} guide={guide} />
            ))}
          </div>
        </section>
      )}

      {empty && !can('author') && <EmptyState>Nothing in this category yet.</EmptyState>}
      {empty && can('author') && (
        <p className="page-header__sub">No guides are filed in this category yet.</p>
      )}

      {dialog === 'landing' && (
        <NewPageDialog
          landingFor={{ id: category.id, name: category.name }}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'category' && (
        <CategoryDialog
          categories={categories}
          category={category}
          onClose={() => setDialog(null)}
        />
      )}
    </>
  )
}

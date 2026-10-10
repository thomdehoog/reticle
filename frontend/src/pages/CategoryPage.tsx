import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'
import { useState } from 'react'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { CategoryDialog } from '../components/CategoryDialog'
import { GuideRow, PageRow } from '../components/GuideRow'
import { IconEdit, IconPlus } from '../components/icons'
import { LazyMarkdownBody } from '../components/LazyMarkdownBody'
import { NewPageDialog } from '../components/NewPageDialog'
import { NotFound } from '../components/RouteStates'
import { EmptyState, StatusBadge } from '../components/ui'
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
  const { data: landing } = useSuspenseQuery(pageQueries.landing(api, category.id))

  const [dialog, setDialog] = useState<'landing' | 'category' | null>(null)

  const children = browsableChildren(categories, category.id)
  const parent = category.parentId
    ? categories.find((candidate) => candidate.id === category.parentId)
    : undefined
  const articles = pages.filter((page) => !page.isLanding)
  const empty = guides.length === 0 && articles.length === 0 && children.length === 0 && !landing

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {parent && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to="/c/$slug" params={{ slug: parent.slug }}>
              {parent.name}
            </Link>
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
        {can('author') && (
          <div className="page-actions">
            {landing && landing.status !== 'published' && <StatusBadge status={landing.status} />}
            {landing ? (
              <Link className="button" to="/w/$id/edit" params={{ id: landing.id }}>
                <IconEdit />
                Edit landing page
              </Link>
            ) : (
              <button className="button" type="button" onClick={() => setDialog('landing')}>
                <IconPlus />
                Write landing page
              </button>
            )}
            {can('admin') && (
              <button className="button" type="button" onClick={() => setDialog('category')}>
                Edit category
              </button>
            )}
          </div>
        )}
      </div>

      {landing && <LandingBody page={landing} />}

      {children.length > 0 && (
        <div className="grid" style={{ margin: '1.5rem 0 2rem' }}>
          {children.map((child) => (
            <Link
              key={child.id}
              to="/c/$slug"
              params={{ slug: child.slug }}
              className="category-card"
            >
              <span className="category-card__name">{child.name}</span>
              {child.description && <span className="category-card__desc">{child.description}</span>}
            </Link>
          ))}
        </div>
      )}

      {articles.length > 0 && (
        <section style={{ marginBottom: '2rem' }}>
          <h2 style={{ marginBottom: '0.75rem' }}>Wiki pages</h2>
          <div className="card">
            {articles.map((page) => (
              <PageRow key={page.id} page={page} />
            ))}
          </div>
        </section>
      )}

      {guides.length > 0 && (
        <section>
          {/* Only needs saying when something else on the page could be
              mistaken for it: a landing page usually embeds guide lists of
              its own, gathered by tag from other categories. */}
          {(landing || articles.length > 0) && (
            <h2 style={{ marginBottom: '0.75rem' }}>Guides in this category</h2>
          )}
          <div className="card">
            {guides.map((guide) => (
              <GuideRow key={guide.id} guide={guide} />
            ))}
          </div>
        </section>
      )}

      {empty && <EmptyState>No guides in this category yet.</EmptyState>}

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

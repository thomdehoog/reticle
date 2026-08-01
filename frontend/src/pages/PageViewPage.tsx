import { Link, useParams } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { IconEdit, IconPrint } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { SectionNav } from '../components/SectionNav'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

/** A wiki page: long-form guidance, with guide lists gathered by tag inside it. */
export function PageViewPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const page = await api.getPage(slug)
      const categories = await api.listCategories()
      /* A standalone article belongs to no section, so there is nothing to list
         beside it — asking for every guide in the institute to discover that is
         not a trade worth making. */
      const [siblings, pages] =
        page.categoryId === null
          ? [[], []]
          : await Promise.all([
              api.listGuides({ categoryId: page.categoryId }),
              api.listPages({ categoryId: page.categoryId }),
            ])
      return { page, categories, siblings, pages }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That page does not exist.</EmptyState>

  const { page, categories, siblings, pages } = data
  const category = categories.find((candidate) => candidate.id === page.categoryId)
  const otherContributors = page.contributors.filter((person) => person.id !== page.author.id)

  return (
    <div className="with-sidebar">
      <SectionNav
        section={category ? { name: category.name, slug: category.slug } : null}
        pages={pages}
        guides={siblings}
        currentId={page.id}
      />

      <article className="guide">
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep">/</span>
        <Link to="/w">Wiki</Link>
        {category && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to={`/c/${category.slug}`}>{category.name}</Link>
          </>
        )}
      </nav>

      {/* A printed wiki page is as capable of being followed off a noticeboard
          two years later as a printed guide, so it carries the same provenance. */}
      <div className="print-only">
        Reticle · ZMB, University of Zurich — {page.title}
        {page.publishedAt &&
          ` · version ${page.version}, published ${new Date(page.publishedAt).toLocaleDateString()}`}
        {` · printed ${new Date().toLocaleDateString()}`}
      </div>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{page.title}</h1>
          {page.summary && <p className="page-header__sub">{page.summary}</p>}
        </div>
        <div className="page-actions">
          {page.status !== 'published' && <StatusBadge status={page.status} />}
          <button className="button" type="button" onClick={() => window.print()}>
            <IconPrint />
            Print
          </button>
          {can('author') && (
            <Link className="button" to={`/w/${page.id}/edit`}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      <div className="guide__meta">
        <div className="guide__meta-item">
          <span className="guide__meta-label">Author</span>
          <span className="guide__meta-value">{page.author.displayName}</span>
        </div>
        {otherContributors.length > 0 && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">
              {otherContributors.length === 1 ? 'Contributor' : 'Contributors'}
            </span>
            <span className="guide__meta-value">
              {otherContributors.map((person) => person.displayName).join(', ')}
            </span>
          </div>
        )}
        {page.viewCount > 0 && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">Read</span>
            <span className="guide__meta-value">
              {page.viewCount.toLocaleString()} {page.viewCount === 1 ? 'time' : 'times'}
            </span>
          </div>
        )}
        {page.publishedAt && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">Version</span>
            <span className="guide__meta-value">
              {page.version} · {new Date(page.publishedAt).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>

      {/* Decorative: the title and the body already say what the page is, and a
          hero that repeats the heading aloud is noise in a screen reader. */}
      {page.heroMediaId && (
        <img className="page-hero" src={`/api/media/${page.heroMediaId}`} alt="" />
      )}

      <MarkdownBody body={page.body} />
      </article>
    </div>
  )
}

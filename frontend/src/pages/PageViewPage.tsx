/**
 * A wiki page as a reader sees it.
 *
 * Long-form guidance rather than a numbered procedure — background, policy,
 * "which objective for which sample" — with tag-gathered guide lists embedded
 * in the prose, so a category page always lists every guide that belongs on it
 * without anybody maintaining the list by hand.
 *
 * It is a separate screen from the guide reader, not a variant of it, because
 * the two are shaped differently: a page has no steps, no pictures with shapes
 * on them and no difficulty, and folding them together would put half of a
 * guide's chrome on a page that has nothing to put in it. What they do share —
 * the provenance line on paper, the version and contributors — comes from the
 * same components, and what else is in the section is in the rail for both.
 */

import { Link, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { IconEdit, IconPrint } from '../components/icons'
import { mediaUrl } from '../domain/types'
import { MarkdownBody } from '../components/MarkdownBody'
import { Revision } from '../components/Revision'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { useAsync } from '../hooks/useAsync'

export function PageViewPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can, organisation } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const page = await api.getPage(slug)
      const categories = await api.listCategories()
      return { page, categories }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That page does not exist.</EmptyState>

  const { page, categories } = data
  const category = categories.find((candidate) => candidate.id === page.categoryId)
  const otherContributors = page.contributors.filter((person) => person.id !== page.author.id)

  return (
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
        {organisation ? `${organisation.name} — ` : ''}{page.title}
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

      {/* The same stamp a guide carries, in the same shape. A wiki page is as
          capable of being out of date as a procedure, and a reader should not
          have to learn a second convention for reading the date on one. */}
      <div className="guide__meta">
        <Revision
          version={page.version}
          publishedAt={page.publishedAt}
          updatedAt={page.updatedAt}
        />
      </div>

      {/* Decorative: the title and the body already say what the page is, and a
          hero that repeats the heading aloud is noise in a screen reader. */}
      {page.heroMediaId && (
        <img className="page-hero" src={mediaUrl(page.heroMediaId)} alt="" />
      )}

      <MarkdownBody body={page.body} />

      {/* The same reasoning as a guide's byline: a name answers "who do I ask
          when this is wrong", which is a question that comes after reading. */}
      <footer className="guide__credits">
        <p className="guide__byline">
          Written by {page.author.displayName}
          {otherContributors.length > 0 &&
            `, with ${otherContributors.map((person) => person.displayName).join(', ')}`}
        </p>
      </footer>
    </article>
  )
}

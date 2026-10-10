import { useApi } from '../api/context'
import { formatDate } from '../domain/dates'
import type { Page } from '../domain/types'
import { LazyMarkdownBody } from './LazyMarkdownBody'

/**
 * A wiki page below its title: hero, text, and who stands behind it.
 *
 * Shared by the reader and the view of a past version, for the same reason
 * `GuideBody` is.
 */
export function PageBody({ page }: { page: Page }) {
  const api = useApi()
  const otherContributors = page.contributors.filter((person) => person.id !== page.author.id)
  const editedByAnother = page.lastEditedBy.id !== page.author.id

  return (
    <>
      {page.heroMediaId && (
        /* The author's description, when they gave one. Empty is a deliberate
           value too — it tells a screen reader the picture is decoration —
           and it is also what a version published before pages could carry a
           description arrives as, since that snapshot has no such field. */
        <img
          className="wiki-hero"
          src={api.mediaDisplayUrl(page.heroMediaId)}
          alt={page.heroAlt ?? ''}
          decoding="async"
        />
      )}

      <LazyMarkdownBody body={page.body} />

      {/* The same provenance a guide carries: who to ask, and how current it is. */}
      <footer className="provenance">
        <p>
          Written by {page.author.displayName}
          {otherContributors.length > 0 &&
            `, with ${otherContributors.map((person) => person.displayName).join(', ')}`}
          .
        </p>
        <p>
          Last edited {formatDate(page.updatedAt)}
          {editedByAnother && ` by ${page.lastEditedBy.displayName}`}
          {page.publishedAt &&
            ` · version ${page.version}, published ${formatDate(page.publishedAt)}`}
          .
        </p>
      </footer>
    </>
  )
}

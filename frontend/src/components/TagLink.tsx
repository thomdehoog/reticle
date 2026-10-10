import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { tagQueries } from '../queries/tags'

/**
 * A tag's display name — "LAS X" for `las-x` — or the slug while the tag list
 * is still on its way, and for a tag no visible guide carries any more.
 *
 * Every chip on a screen reads the one cached list, so a page of thirty guide
 * rows costs one request, not thirty.
 */
export function useTagName(slug: string): string {
  const api = useApi()
  const { data } = useQuery({
    ...tagQueries.list(api),
    select: (tags) => tags.find((tag) => tag.slug === slug)?.name,
  })
  return data ?? slug
}

/** A tag as a way to somewhere: every chip leads to the guides that carry it. */
export function TagLink({ slug }: { slug: string }) {
  const name = useTagName(slug)
  return (
    <Link className="tag" to="/t/$tag" params={{ tag: slug }}>
      {name}
    </Link>
  )
}

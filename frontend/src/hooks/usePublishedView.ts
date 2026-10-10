/**
 * Which copy of a guide or page a reader screen should draw.
 *
 * The rule the reader screens share: **show what readers see.** A viewer is
 * only ever sent the published version, so for a viewer there is nothing to
 * decide. An author is sent the working copy — the editor needs it — and when
 * that has moved on from the published version, the reader screen fetches the
 * published one as well and shows that, unless the author has asked for a
 * preview of their changes.
 */

import { useQuery, type UseQueryOptions } from '@tanstack/react-query'

interface Publishable {
  hasUnpublishedChanges: boolean
}

export interface PublishedView<T> {
  /** The document to draw, or null while the published one is still arriving. */
  shown: T | null
  /** True when `shown` is the working copy of something whose readers see an older version. */
  previewing: boolean
  /** True when `shown` is the published version and newer work exists. */
  behind: boolean
}

export function usePublishedView<T extends Publishable, K extends readonly unknown[]>(
  /** What the server sends this person by default. */
  given: T,
  /** The query for the published version; only run when it is needed. */
  publishedQuery: UseQueryOptions<T, Error, T, K>,
  /** Whether the author asked to see their changes instead. */
  preview: boolean,
): PublishedView<T> {
  const wanted = given.hasUnpublishedChanges && !preview
  const published = useQuery({ ...publishedQuery, enabled: wanted })

  if (!given.hasUnpublishedChanges) return { shown: given, previewing: false, behind: false }
  if (preview) return { shown: given, previewing: true, behind: false }
  if (published.data) return { shown: published.data, previewing: false, behind: true }
  /* The published version could not be had — it was unpublished a moment ago,
     say. What there is to show is the working copy, labelled as what it is. */
  if (published.isError) return { shown: given, previewing: true, behind: false }
  return { shown: null, previewing: false, behind: false }
}

import {
  queryOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { GuideQuery, ReticleApi } from '../api/reticle'
import type { Guide } from '../domain/types'
import { searchKeys } from './search'
import { tagKeys } from './tags'

export const guideKeys = {
  all: ['guides'] as const,
  lists: () => [...guideKeys.all, 'list'] as const,
  list: (query: GuideQuery) => [...guideKeys.lists(), query] as const,
  details: () => [...guideKeys.all, 'detail'] as const,
  /** Readers arrive by slug and the editor by id, so both spellings are keys. */
  detail: (idOrSlug: string) => [...guideKeys.details(), idOrSlug] as const,
}

export const guideQueries = {
  list: (api: ReticleApi, query: GuideQuery = {}) =>
    queryOptions({
      queryKey: guideKeys.list(query),
      queryFn: () => api.listGuides(query),
    }),

  detail: (api: ReticleApi, idOrSlug: string) =>
    queryOptions({
      queryKey: guideKeys.detail(idOrSlug),
      queryFn: () => api.getGuide(idOrSlug),
    }),
}

function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().join('\n') === [...b].sort().join('\n')
}

/**
 * Brings the cache in line with a guide the server has just returned.
 *
 * The response *is* the new truth for the guide itself, so it is written
 * straight into both of its keys instead of being refetched — which also means
 * an autosave never triggers a read of the document being edited. Everything
 * derived from it is invalidated: every listing (title, status and order all
 * show there), search, and the tag list when the tags or the visibility that
 * tag counts depend on actually changed.
 */
function guideWritten(queryClient: QueryClient, guide: Guide): void {
  const previous = queryClient.getQueryData<Guide>(guideKeys.detail(guide.id))
  const tagsAffected =
    !previous || previous.status !== guide.status || !sameTags(previous.tags, guide.tags)

  queryClient.setQueryData(guideKeys.detail(guide.id), guide)
  queryClient.setQueryData(guideKeys.detail(guide.slug), guide)

  void queryClient.invalidateQueries({
    queryKey: guideKeys.all,
    predicate: ({ queryKey }) =>
      !(queryKey[1] === 'detail' && (queryKey[2] === guide.id || queryKey[2] === guide.slug)),
  })
  void queryClient.invalidateQueries({ queryKey: searchKeys.all })
  if (tagsAffected) void queryClient.invalidateQueries({ queryKey: tagKeys.all })
}

export function useCreateGuide() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ title, categoryId }: { title: string; categoryId: string }) =>
      api.createGuide(title, categoryId),
    onSuccess: (guide) => guideWritten(queryClient, guide),
  })
}

/** The whole-document save behind autosave; see `hooks/useAutosave`. */
export function useSaveGuide() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (guide: Guide) => api.saveGuide(guide),
    onSuccess: (saved) => guideWritten(queryClient, saved),
  })
}

export function usePublishGuide() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.publishGuide(id),
    onSuccess: (published) => guideWritten(queryClient, published),
  })
}

export function useUnpublishGuide() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.unpublishGuide(id),
    onSuccess: (draft) => guideWritten(queryClient, draft),
  })
}

/**
 * Archived content answers 404 from then on, so its cached copies are removed
 * outright rather than refetched into an error.
 */
export function useArchiveGuide() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (guide: Pick<Guide, 'id' | 'slug'>) => api.archiveGuide(guide.id),
    onSuccess: (_, guide) => {
      queryClient.removeQueries({ queryKey: guideKeys.detail(guide.id) })
      queryClient.removeQueries({ queryKey: guideKeys.detail(guide.slug) })
      void queryClient.invalidateQueries({ queryKey: guideKeys.lists() })
      void queryClient.invalidateQueries({ queryKey: searchKeys.all })
      void queryClient.invalidateQueries({ queryKey: tagKeys.all })
    },
  })
}

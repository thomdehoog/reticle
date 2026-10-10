import {
  queryOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { NewPageInput, PageQuery, ReticleApi } from '../api/reticle'
import type { Page } from '../domain/types'
import { searchKeys } from './search'

export const pageKeys = {
  all: ['pages'] as const,
  lists: () => [...pageKeys.all, 'list'] as const,
  list: (query: PageQuery) => [...pageKeys.lists(), query] as const,
  details: () => [...pageKeys.all, 'detail'] as const,
  detail: (idOrSlug: string) => [...pageKeys.details(), idOrSlug] as const,
  /**
   * A category's landing page is a page, so it is keyed with the pages: saving
   * or publishing one then refreshes the category that shows it without the
   * page mutations having to know categories exist.
   */
  landings: () => [...pageKeys.all, 'landing'] as const,
  landing: (categoryId: string) => [...pageKeys.landings(), categoryId] as const,
}

export const pageQueries = {
  list: (api: ReticleApi, query: PageQuery = {}) =>
    queryOptions({
      queryKey: pageKeys.list(query),
      queryFn: () => api.listPages(query),
    }),

  detail: (api: ReticleApi, idOrSlug: string) =>
    queryOptions({
      queryKey: pageKeys.detail(idOrSlug),
      queryFn: () => api.getPage(idOrSlug),
    }),

  /** Resolves to `null`, not an error, when the category has no landing page. */
  landing: (api: ReticleApi, categoryId: string) =>
    queryOptions({
      queryKey: pageKeys.landing(categoryId),
      queryFn: () => api.getCategoryLandingPage(categoryId),
    }),
}

/** The page counterpart of `guideWritten` in `queries/guides`. */
function pageWritten(queryClient: QueryClient, page: Page): void {
  queryClient.setQueryData(pageKeys.detail(page.id), page)
  queryClient.setQueryData(pageKeys.detail(page.slug), page)

  void queryClient.invalidateQueries({
    queryKey: pageKeys.all,
    predicate: ({ queryKey }) =>
      !(queryKey[1] === 'detail' && (queryKey[2] === page.id || queryKey[2] === page.slug)),
  })
  void queryClient.invalidateQueries({ queryKey: searchKeys.all })
}

export function useCreatePage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: NewPageInput) => api.createPage(input),
    onSuccess: (page) => pageWritten(queryClient, page),
  })
}

export function useSavePage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (page: Page) => api.savePage(page),
    onSuccess: (saved) => pageWritten(queryClient, saved),
  })
}

export function usePublishPage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.publishPage(id),
    onSuccess: (published) => pageWritten(queryClient, published),
  })
}

export function useUnpublishPage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.unpublishPage(id),
    onSuccess: (draft) => pageWritten(queryClient, draft),
  })
}

export function useArchivePage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (page: Pick<Page, 'id' | 'slug'>) => api.archivePage(page.id),
    onSuccess: (_, page) => {
      queryClient.removeQueries({ queryKey: pageKeys.detail(page.id) })
      queryClient.removeQueries({ queryKey: pageKeys.detail(page.slug) })
      void queryClient.invalidateQueries({ queryKey: pageKeys.lists() })
      void queryClient.invalidateQueries({ queryKey: pageKeys.landings() })
      void queryClient.invalidateQueries({ queryKey: searchKeys.all })
    },
  })
}

import {
  queryOptions,
  useMutation,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { NewPageInput, PageQuery, ReticleApi } from '../api/reticle'
import type { ContentView, Page } from '../domain/types'
import { searchKeys } from './search'

export const pageKeys = {
  all: ['pages'] as const,
  lists: () => [...pageKeys.all, 'list'] as const,
  list: (query: PageQuery) => [...pageKeys.lists(), query] as const,
  details: () => [...pageKeys.all, 'detail'] as const,
  detail: (idOrSlug: string) => [...pageKeys.details(), idOrSlug] as const,
  /** See `guideKeys.published`. */
  published: (idOrSlug: string) => [...pageKeys.all, 'published', idOrSlug] as const,
  /**
   * A category's landing page is a page, so it is keyed with the pages: saving
   * or publishing one then refreshes the category that shows it without the
   * page mutations having to know categories exist.
   */
  landings: () => [...pageKeys.all, 'landing'] as const,
  landing: (categoryId: string, view: ContentView | 'default' = 'default') =>
    [...pageKeys.landings(), categoryId, view] as const,
  /** See `guideKeys.revisions`. */
  revisions: (id: string) => [...pageKeys.all, 'revisions', id] as const,
  revision: (id: string, version: number) => [...pageKeys.revisions(id), version] as const,
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

  /** Exactly what a viewer gets; see `guideQueries.published`. */
  published: (api: ReticleApi, idOrSlug: string) =>
    queryOptions({
      queryKey: pageKeys.published(idOrSlug),
      queryFn: () => api.getPage(idOrSlug, 'published'),
    }),

  /**
   * Resolves to `null`, not an error, when the category has no landing page.
   * Without a `view` it is what this person is given by default; an author
   * asks with `'published'` for the landing page readers actually have.
   */
  landing: (api: ReticleApi, categoryId: string, view?: ContentView) =>
    queryOptions({
      queryKey: pageKeys.landing(categoryId, view),
      queryFn: () => api.getCategoryLandingPage(categoryId, view),
    }),

  revisions: (api: ReticleApi, id: string) =>
    queryOptions({
      queryKey: pageKeys.revisions(id),
      queryFn: () => api.listPageRevisions(id),
    }),

  revision: (api: ReticleApi, id: string, version: number) =>
    queryOptions({
      queryKey: pageKeys.revision(id, version),
      queryFn: () => api.getPageRevision(id, version),
      staleTime: Infinity,
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

export function useRevertPage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.revertPage(id),
    onSuccess: (reverted) => pageWritten(queryClient, reverted),
  })
}

export function useArchivePage() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (page: Pick<Page, 'id' | 'slug'>) => api.archivePage(page.id),
    onSuccess: (_, page) => {
      for (const key of [page.id, page.slug]) {
        queryClient.removeQueries({ queryKey: pageKeys.detail(key) })
        queryClient.removeQueries({ queryKey: pageKeys.published(key) })
      }
      void queryClient.invalidateQueries({ queryKey: pageKeys.lists() })
      void queryClient.invalidateQueries({ queryKey: pageKeys.landings() })
      void queryClient.invalidateQueries({ queryKey: searchKeys.all })
    },
  })
}

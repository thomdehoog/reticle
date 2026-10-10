import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { CategoryChanges, CategoryInput, ReticleApi } from '../api/reticle'
import type { OrderChange } from '../domain/category'

export const categoryKeys = {
  all: ['categories'] as const,
  list: () => [...categoryKeys.all, 'list'] as const,
}

export const categoryQueries = {
  /** The flat list; `domain/category` turns it into a tree where one is needed. */
  list: (api: ReticleApi) =>
    queryOptions({
      queryKey: categoryKeys.list(),
      queryFn: () => api.listCategories(),
    }),
}

/* Every category change redraws the same things — the tree, the breadcrumbs,
   the pickers — and they are all derived from the one list, so each mutation
   invalidates exactly that. */

export function useCreateCategory() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: CategoryInput) => api.createCategory(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: categoryKeys.all }),
  })
}

export function useUpdateCategory() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: CategoryChanges }) =>
      api.updateCategory(id, changes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: categoryKeys.all }),
  })
}

export function useDeleteCategory() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.deleteCategory(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: categoryKeys.all }),
  })
}

/**
 * Writes a new sibling order. One request per row that moved, in sequence:
 * there is no bulk endpoint, and for the usual nudge that is two small PATCHes.
 * The list is refetched whether or not they all landed, so what is on screen
 * is what the server holds even after a failure half-way.
 */
export function useReorderCategories() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (changes: OrderChange[]) => {
      for (const { id, orderIndex } of changes) {
        await api.updateCategory(id, { orderIndex })
      }
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: categoryKeys.all }),
  })
}

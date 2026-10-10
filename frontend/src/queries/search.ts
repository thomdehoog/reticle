import { queryOptions } from '@tanstack/react-query'

import type { ReticleApi } from '../api/reticle'
import type { SearchResult } from '../domain/types'

export const searchKeys = {
  all: ['search'] as const,
  results: (term: string) => [...searchKeys.all, term] as const,
}

export const searchQueries = {
  /**
   * An empty term is answered locally. The server would say `[]` as well, but
   * the search page is reachable with no term at all and that should not cost
   * a request.
   */
  results: (api: ReticleApi, term: string) => {
    const trimmed = term.trim()
    return queryOptions({
      queryKey: searchKeys.results(trimmed),
      queryFn: (): Promise<SearchResult[]> =>
        trimmed === '' ? Promise.resolve([]) : api.search(trimmed),
    })
  },
}

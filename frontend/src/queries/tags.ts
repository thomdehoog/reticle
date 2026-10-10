import { queryOptions } from '@tanstack/react-query'

import type { ReticleApi } from '../api/reticle'

export const tagKeys = {
  all: ['tags'] as const,
  list: () => [...tagKeys.all, 'list'] as const,
}

/**
 * Tags have no endpoints of their own to write to: they come into being when a
 * guide is saved with one and fade when no visible guide carries them. So this
 * list is invalidated by the guide mutations, not by anything in this module.
 */
export const tagQueries = {
  list: (api: ReticleApi) =>
    queryOptions({
      queryKey: tagKeys.list(),
      queryFn: () => api.listTags(),
    }),
}

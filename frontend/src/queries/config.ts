import { queryOptions, useQuery } from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { ReticleApi } from '../api/reticle'
import { DEFAULT_UPLOAD_LIMITS, type UploadLimits } from '../domain/media'

export const configKeys = {
  all: ['config'] as const,
  limits: () => [...configKeys.all, 'limits'] as const,
}

export const configQueries = {
  /**
   * Changes only when the operator edits the environment and restarts the
   * server, so one answer serves the whole visit; a tab left open across such
   * a restart is corrected by the server refusing the upload, as it always
   * would have.
   */
  limits: (api: ReticleApi) =>
    queryOptions({
      queryKey: configKeys.limits(),
      queryFn: () => api.getUploadLimits(),
      staleTime: Infinity,
    }),
}

/**
 * The upload limits to check a file against, right now.
 *
 * Never undefined: until the server has answered — and if it never does — the
 * documented defaults stand in. A wrong guess costs little either way, because
 * these checks are a courtesy and the server has the last word on every file.
 */
export function useUploadLimits(): UploadLimits {
  const api = useApi()
  return useQuery(configQueries.limits(api)).data ?? DEFAULT_UPLOAD_LIMITS
}

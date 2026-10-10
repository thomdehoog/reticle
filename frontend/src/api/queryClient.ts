import { QueryClient } from '@tanstack/react-query'

import { ApiError } from './client'

/** How long a read is trusted before it is quietly refreshed in the background. */
const READ_STALE_MS = 30_000

const MAX_TRANSIENT_RETRIES = 2

/**
 * Only a failure that might not happen twice is worth a second request. A 4xx
 * is the server's considered answer — asking again for a guide that does not
 * exist, or one this user may not read, just delays the message by a few
 * seconds and triples the traffic.
 */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (!(error instanceof ApiError) || !error.isTransient) return false
  return failureCount < MAX_TRANSIENT_RETRIES
}

export interface QueryClientSettings {
  /**
   * Tests turn retries off: a deliberately failing request should fail the
   * assertion now, not after the back-off has run out the clock.
   */
  retry?: boolean
}

export function createQueryClient({ retry = true }: QueryClientSettings = {}): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: READ_STALE_MS,
        retry: retry ? shouldRetry : false,
      },
      /* Never retried: a save that was refused with `conflict` must stay
         refused, and a repeated POST is a repeated side effect. */
      mutations: { retry: false },
    },
  })
}

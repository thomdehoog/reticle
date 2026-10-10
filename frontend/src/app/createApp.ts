/**
 * Builds the pieces every Reticle screen shares: the one HTTP client, the
 * query cache in front of it, and the browser history the router will use.
 *
 * A function rather than module-level singletons so that a test can build the
 * same application around an in-memory server and an in-memory address bar —
 * the wiring under test is then the wiring that ships.
 */

import type { QueryClient } from '@tanstack/react-query'
import { createBrowserHistory, type RouterHistory } from '@tanstack/react-router'

import { ApiClient } from '../api/client'
import { createQueryClient } from '../api/queryClient'
import { ReticleApi } from '../api/reticle'
import { endSession } from '../auth/session'

export interface ReticleApp {
  api: ReticleApi
  queryClient: QueryClient
  history: RouterHistory
}

export interface ReticleAppOptions {
  /**
   * Replaces the network transport. Tests point this at an in-memory server so
   * components exercise the real client, the real headers and the real error
   * mapping; nothing in production should ever set it.
   */
  fetchImpl?: typeof fetch
  /** Replaces the browser's address bar, for tests. */
  history?: RouterHistory
  /** Off in tests; see `createQueryClient`. */
  retry?: boolean
}

export function createReticleApp(options: ReticleAppOptions = {}): ReticleApp {
  const queryClient = createQueryClient({ retry: options.retry })

  const http = new ApiClient({
    fetchImpl: options.fetchImpl,
    /* Whichever request discovers the session has gone — a page load, a
       background refetch, an autosave — the result is the same: back to the
       login screen, with nothing of the old session left in the cache. */
    onUnauthenticated: () => endSession(queryClient),
  })

  return {
    api: new ReticleApi(http),
    queryClient,
    history: options.history ?? createBrowserHistory(),
  }
}

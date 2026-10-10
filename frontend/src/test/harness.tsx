import { RouterContextProvider, createMemoryHistory } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'

import { App } from '../App'
import { AppProviders } from '../app/AppProviders'
import { createReticleApp } from '../app/createApp'
import { createAppRouter } from '../router'
import type { FakeServer } from './fakeServer'

function createTestApp(fetchImpl: typeof fetch, route: string) {
  return createReticleApp({
    fetchImpl,
    history: createMemoryHistory({ initialEntries: [route] }),
    retry: false,
  })
}

/**
 * Mounts the whole application at a URL, against the in-memory server.
 *
 * Page tests go through this rather than rendering a page component on its
 * own: the session gate, the route table, the loaders and the role guards are
 * then the real ones, and a page that only works when hand-fed its params
 * cannot pass.
 */
export function renderApp({ route = '/', server }: { route?: string; server: FakeServer }) {
  const app = createTestApp(server.fetchImpl, route)
  const view = render(
    <AppProviders app={app}>
      <App app={app} />
    </AppProviders>,
  )
  return {
    ...view,
    app,
    /** Where the address bar points now, path and query together. */
    location: () => app.history.location.href,
  }
}

/**
 * Mounts one component with everything it may reach for — the client, the
 * query cache, and a router for its links — but no session gate and no routes.
 * For components that are not pages.
 */
export function renderWithApp(
  ui: ReactNode,
  { route = '/', fetchImpl }: { route?: string; fetchImpl: typeof fetch },
) {
  const app = createTestApp(fetchImpl, route)
  const router = createAppRouter({ api: app.api, queryClient: app.queryClient }, app.history)
  const view = render(
    <AppProviders app={app}>
      <RouterContextProvider router={router}>{ui}</RouterContextProvider>
    </AppProviders>,
  )
  return { ...view, app, location: () => app.history.location.href }
}

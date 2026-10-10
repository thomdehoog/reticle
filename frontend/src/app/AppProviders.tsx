import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ApiContext } from '../api/context'
import type { ReticleApp } from './createApp'

/** Makes the client and the query cache available to everything beneath. */
export function AppProviders({ app, children }: { app: ReticleApp; children: ReactNode }) {
  return (
    <QueryClientProvider client={app.queryClient}>
      <ApiContext.Provider value={app.api}>{children}</ApiContext.Provider>
    </QueryClientProvider>
  )
}

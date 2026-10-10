import { createContext, useContext } from 'react'

import type { ReticleApi } from './reticle'

/**
 * Hands the one typed client to whatever needs it.
 *
 * A context rather than a module-level singleton, because tests build a client
 * around an in-memory transport: the instance has to be something a test can
 * supply, and nothing in the app may reach around it to a global.
 */
export const ApiContext = createContext<ReticleApi | null>(null)

export function useApi(): ReticleApi {
  const api = useContext(ApiContext)
  if (!api) throw new Error('useApi must be used inside AppProviders')
  return api
}

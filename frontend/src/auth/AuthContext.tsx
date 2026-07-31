/**
 * Session state for the whole application.
 *
 * Reticle has no anonymous access, so this provider sits above the router: the
 * first thing the app does is ask the server who it is talking to, and nothing
 * else renders until that question is answered.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { ApiClient } from '../api/client'
import { ReticleApi } from '../api/reticle'
import type { Role, User } from '../domain/types'

type SessionStatus = 'checking' | 'authenticated' | 'anonymous'

interface AuthContextValue {
  status: SessionStatus
  user: User | null
  api: ReticleApi
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  /** Role check used to hide controls; the server enforces the real rule. */
  can: (minimum: Role) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

const ROLE_RANK: Record<Role, number> = { viewer: 0, author: 1, admin: 2 }

interface AuthProviderProps {
  children: ReactNode
  /**
   * Replaces the network transport. Tests point this at an in-memory server so
   * components exercise the real client, the real headers and the real error
   * mapping; nothing in production should ever set it.
   */
  fetchImpl?: typeof fetch
}

export function AuthProvider({ children, fetchImpl }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<SessionStatus>('checking')

  const api = useMemo(() => {
    const http = new ApiClient({
      fetchImpl,
      onUnauthenticated: () => {
        setUser(null)
        setStatus('anonymous')
      },
    })
    return new ReticleApi(http)
  }, [fetchImpl])

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      })
      .catch(() => {
        if (cancelled) return
        setUser(null)
        setStatus('anonymous')
      })
    return () => {
      cancelled = true
    }
  }, [api])

  const login = useCallback(
    async (email: string, password: string) => {
      const me = await api.login(email, password)
      setUser(me)
      setStatus('authenticated')
    },
    [api],
  )

  /**
   * The local session is cleared even if the server call fails, so a user who
   * asks to log out on a flaky connection is never left looking logged in.
   */
  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
      setStatus('anonymous')
    }
  }, [api])

  const can = useCallback(
    (minimum: Role) => (user ? ROLE_RANK[user.role] >= ROLE_RANK[minimum] : false),
    [user],
  )

  const value = useMemo(
    () => ({ status, user, api, login, logout, can }),
    [status, user, api, login, logout, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside an AuthProvider')
  return context
}

export function useApi(): ReticleApi {
  return useAuth().api
}

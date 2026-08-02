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

import { ApiClient, ApiError } from '../api/client'
import { ReticleApi } from '../api/reticle'
import type { Organisation, Role, User } from '../domain/types'

type SessionStatus = 'checking' | 'authenticated' | 'anonymous' | 'unreachable'

interface AuthContextValue {
  status: SessionStatus
  /** Whose instance this is, once it has said. */
  organisation: Organisation | null
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
  /* Asked for before anyone signs in: the login screen has to say which
     facility it belongs to, and one Reticle per facility is the intended
     shape. Null until it answers, so nothing renders somebody else's name. */
  const [organisation, setOrganisation] = useState<Organisation | null>(null)

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
    /* Deliberately not blocking the session check: whose instance this is and
       who you are are independent questions, and a slow answer to one must not
       hold up the other. */
    api
      .configuration()
      .then((config) => {
        if (!cancelled) setOrganisation(config.organisation)
      })
      .catch(() => {
        /* An instance that cannot say its own name still works; the header
           falls back to the product name rather than showing an error. */
      })
    return () => {
      cancelled = true
    }
  }, [api])

  useEffect(() => {
    let cancelled = false
    api
      .me()
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setStatus('authenticated')
      })
      .catch((cause: unknown) => {
        if (cancelled) return
        setUser(null)
        /*
         * "Not signed in" and "could not ask" are different answers, and only
         * one of them means show the login screen.
         *
         * This used to treat every failure as the first, so a rate-limited
         * reply, a 500, or a lost connection at page load signed the reader
         * out — and the rate limiter is the likely one, because a whole
         * institute behind one address shares its budget. The limiter's own
         * docstring promises it must never lock the facility out; the server
         * kept that promise and the client broke it, by throwing away the ten
         * error codes the client had carefully distinguished.
         */
        const refused = cause instanceof ApiError && cause.code === 'not_authenticated'
        setStatus(refused ? 'anonymous' : 'unreachable')
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
    () => ({ status, user, organisation, api, login, logout, can }),
    [status, user, organisation, api, login, logout, can],
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

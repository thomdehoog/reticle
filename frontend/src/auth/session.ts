/**
 * Who the app is talking to.
 *
 * The session is a query like any other read — `GET /auth/me` — rather than a
 * separate piece of React state, so there is one answer to "is anyone signed
 * in" and every screen, route guard and background request reads the same one.
 */

import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { useCallback } from 'react'

import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import type { ReticleApi } from '../api/reticle'
import type { Role, User } from '../domain/types'

export const authKeys = {
  all: ['auth'] as const,
  me: () => [...authKeys.all, 'me'] as const,
}

/**
 * Resolves to `null` for "nobody is signed in". That is an ordinary answer, not
 * a failure: the app's first request is always this one, and for a visitor
 * without a session the server's 401 is the expected reply.
 *
 * Never stale, because nothing about it changes behind the app's back that a
 * refetch would catch sooner than the next real request does — an expired
 * session announces itself as a 401 on whatever is asked next.
 */
export function sessionQuery(api: ReticleApi) {
  return queryOptions({
    queryKey: authKeys.me(),
    queryFn: async (): Promise<User | null> => {
      try {
        return await api.me()
      } catch (cause) {
        if (cause instanceof ApiError && cause.code === 'not_authenticated') return null
        throw cause
      }
    },
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

const ROLE_RANK: Record<Role, number> = { viewer: 0, author: 1, admin: 2 }

export function roleAtLeast(role: Role, minimum: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum]
}

function isSessionQuery(queryKey: readonly unknown[]): boolean {
  return queryKey[0] === authKeys.all[0]
}

/**
 * Forgets everything that was fetched on behalf of a user.
 *
 * Facility workstations are shared: the next person to sign in on this browser
 * tab may be a viewer following an admin, and must never be shown — even for
 * one frame, from cache — a draft or a people list the previous session loaded.
 */
export function forgetUserData(queryClient: QueryClient): void {
  const others = {
    predicate: (query: { queryKey: readonly unknown[] }) => !isSessionQuery(query.queryKey),
  }
  void queryClient.cancelQueries(others)
  queryClient.removeQueries(others)
}

/** Drops to the login screen. Safe to call repeatedly and from outside React. */
export function endSession(queryClient: QueryClient): void {
  queryClient.setQueryData(authKeys.me(), null)
  forgetUserData(queryClient)
}

type SessionStatus = 'checking' | 'authenticated' | 'anonymous'

export interface Session {
  status: SessionStatus
  user: User | null
  /** Role check used to hide controls; the server enforces the real rule. */
  can: (minimum: Role) => boolean
}

export function useSession(): Session {
  const api = useApi()
  const { data, isPending } = useQuery(sessionQuery(api))
  const user = data ?? null

  const can = useCallback(
    (minimum: Role) => (user ? roleAtLeast(user.role, minimum) : false),
    [user],
  )

  /* A session check that failed outright (server down) lands on the login
     screen too: its form is the one place that explains a connection problem
     and offers a way to try again. */
  const status: SessionStatus = isPending ? 'checking' : user ? 'authenticated' : 'anonymous'

  return { status, user, can }
}

export function useLogin() {
  const api = useApi()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      api.login(email, password),
    /* Mutations keep their variables for inspection; a password is not
       something to leave sitting in a cache once the request has gone. */
    gcTime: 0,
    onSuccess: (user) => {
      forgetUserData(queryClient)
      queryClient.setQueryData(authKeys.me(), user)
    },
  })
}

/**
 * The local session is cleared even if the server call fails, so a user who
 * asks to log out on a flaky connection is never left looking logged in.
 */
export function useLogout() {
  const api = useApi()
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => api.logout(),
    onSettled: () => endSession(queryClient),
  })
}

import { RouterProvider } from '@tanstack/react-router'
import { useMemo } from 'react'

import type { ReticleApp } from './app/createApp'
import { useSession } from './auth/session'
import { LoginPage } from './pages/LoginPage'
import { createAppRouter } from './router'

/**
 * Reticle has no public surface, so an unauthenticated visitor gets the login
 * screen whatever the URL says. Keeping the requested path in the address bar
 * means that after logging in, the router simply resolves the page they
 * originally asked for — no redirect dance, no "returnTo" parameter to leak.
 *
 * That is also why the session gate sits outside the router instead of in a
 * route guard: a guard would have to navigate somewhere to show the form, and
 * here nothing navigates at all.
 */
export function App({ app }: { app: ReticleApp }) {
  const { status, user } = useSession()

  if (status === 'checking') {
    return <div className="spinner">Loading Reticle…</div>
  }

  if (!user) {
    return <LoginPage />
  }

  return <SignedIn app={app} userId={user.id} />
}

/**
 * A router per signed-in session, over the one shared history.
 *
 * A router remembers the routes it has loaded. Building a new one when the
 * user changes means the next person to sign in on a shared workstation starts
 * from the URL alone: their role guards run from scratch, and nothing the
 * previous session matched or loaded is there to be shown first.
 */
function SignedIn({ app, userId }: { app: ReticleApp; userId: string }) {
  const router = useMemo(
    () => createAppRouter({ api: app.api, queryClient: app.queryClient }, app.history),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [app, userId],
  )

  return <RouterProvider router={router} />
}

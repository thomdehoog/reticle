/**
 * The map from a web address to a screen.
 *
 * Every address the application understands is listed here once: `/g/something`
 * is a guide, `/w/something` is a wiki page, `/search` is the search results.
 * React Router matches the address in the browser's bar against this list and
 * draws the matching screen.
 *
 * Keeping the whole list in one small file means you can answer "what pages does
 * this thing have?" by reading twenty lines, and you cannot add a page that
 * nobody can reach.
 */

import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'

import { AppShell } from './components/AppShell'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useAuth } from './auth/AuthContext'
import type { Role } from './domain/types'
import { AccountPage } from './pages/AccountPage'
import { CategoriesPage } from './pages/CategoriesPage'
import { SectionFormPage } from './pages/SectionFormPage'
import { CategoryPage } from './pages/CategoryPage'
import { GuideEditorPage } from './pages/GuideEditorPage'
import { GuideViewPage } from './pages/GuideViewPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { PageEditorPage } from './pages/PageEditorPage'
import { PageViewPage } from './pages/PageViewPage'
import { SearchPage } from './pages/SearchPage'
import { TagIndexPage } from './pages/TagIndexPage'
import { TagPage } from './pages/TagPage'
import { UsersPage } from './pages/UsersPage'
import { WikiIndexPage } from './pages/WikiIndexPage'

/**
 * Reading is public, so a visitor who is not signed in gets the site rather
 * than a login screen. Signing in is what unlocks writing, and `/login` is the
 * one address that asks for it — reached from the header, or from an editing
 * address somebody typed without a session.
 *
 * The editing routes are the only ones that turn a visitor away, and they send
 * them to the login screen rather than home: arriving at an edit URL is a
 * statement of intent, and answering it with the front page loses what they
 * were trying to do.
 */
/**
 * A screen that needs an account, and what to do with somebody who lacks one.
 *
 * The two outcomes are deliberately different. Nobody signed in is *asked* to
 * sign in, at the address they were heading for. Somebody signed in whose role
 * is too junior is sent home, because there is nothing for them to do about it
 * and a login form would imply there is.
 *
 * None of this is a security boundary — the server refuses these calls whatever
 * the browser renders. It is what stops an author being shown an editor that
 * cannot save.
 */
function Guarded({ role, children }: { role: Role; children: ReactNode }) {
  const { status, can } = useAuth()

  if (status !== 'authenticated') return <Navigate to="/login" replace />
  if (!can(role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export function App() {
  const { status } = useAuth()
  // Keying the boundary on the path gives it a fresh instance per page, so a
  // guide that fails to render does not leave every subsequent page showing
  // that guide's error. Navigating away is the recovery; re-rendering the same
  // broken page in place would only loop.
  const { pathname } = useLocation()

  if (status === 'checking') {
    return <div className="spinner">Loading Reticle…</div>
  }

  /* The server could not be asked, which is not the same as being signed out.
     Showing the login screen here tells somebody their session has ended when
     it has not, and invites them to type a password at a server that is busy
     or unreachable. Say what happened and offer the only thing that helps. */
  if (status === 'unreachable') {
    return (
      <div className="page-state">
        <h1>Reticle cannot be reached</h1>
        <p>
          The server did not answer when we checked your session. You are probably still
          signed in — this is usually a moment&apos;s interruption.
        </p>
        <button className="button button--primary" type="button" onClick={() => window.location.reload()}>
          Try again
        </button>
      </div>
    )
  }

  return (
    <AppShell>
      <ErrorBoundary scope="content" key={pathname}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/c/:slug" element={<CategoryPage />} />
          <Route path="/g/:slug" element={<GuideViewPage />} />
          <Route path="/w" element={<WikiIndexPage />} />
          <Route path="/w/:slug" element={<PageViewPage />} />
          <Route path="/t" element={<TagIndexPage />} />
          <Route path="/t/:tag" element={<TagPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/login" element={status === 'authenticated' ? <Navigate to="/" replace /> : <LoginPage />} />

          {/* Everything below needs an account. A visitor is sent to the login
              screen rather than to the front page, because typing an editing
              address says what they came to do and the front page discards it.
              An account that is signed in but too junior goes home instead:
              they are not being asked for anything, they simply cannot. */}
          <Route path="/g/:id/edit" element={<Guarded role="author"><GuideEditorPage /></Guarded>} />
          <Route path="/w/:id/edit" element={<Guarded role="author"><PageEditorPage /></Guarded>} />
          <Route path="/account" element={<Guarded role="viewer"><AccountPage /></Guarded>} />
          <Route path="/users" element={<Guarded role="admin"><UsersPage /></Guarded>} />
          <Route path="/categories" element={<Guarded role="admin"><CategoriesPage /></Guarded>} />
          {/* Before `/categories/:id/edit` would matter either way — these two
              cannot collide, `new` being a literal — but the pair reads as one
              screen and is written as one. */}
          <Route path="/categories/new" element={<Guarded role="admin"><SectionFormPage /></Guarded>} />
          <Route path="/categories/:id/edit" element={<Guarded role="admin"><SectionFormPage /></Guarded>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}

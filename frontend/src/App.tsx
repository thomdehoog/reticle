import { Navigate, Route, Routes, useLocation } from 'react-router'

import { AppShell } from './components/AppShell'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useAuth } from './auth/AuthContext'
import { AccountPage } from './pages/AccountPage'
import { CategoriesPage } from './pages/CategoriesPage'
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
 * Reticle has no public surface, so an unauthenticated visitor gets the login
 * screen whatever the URL says. Keeping the requested path in the address bar
 * means that after logging in, the very same render tree resolves the page they
 * originally asked for — no redirect dance, no "returnTo" parameter to leak.
 */
export function App() {
  const { status, can } = useAuth()
  // Keying the boundary on the path gives it a fresh instance per page, so a
  // guide that fails to render does not leave every subsequent page showing
  // that guide's error. Navigating away is the recovery; re-rendering the same
  // broken page in place would only loop.
  const { pathname } = useLocation()

  if (status === 'checking') {
    return <div className="spinner">Loading Reticle…</div>
  }

  if (status === 'anonymous') {
    return <LoginPage />
  }

  return (
    <AppShell>
      <ErrorBoundary scope="content" key={pathname}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/c/:slug" element={<CategoryPage />} />
          <Route path="/g/:slug" element={<GuideViewPage />} />
          <Route path="/g/:id/edit" element={<GuideEditorPage />} />
          <Route path="/w" element={<WikiIndexPage />} />
          <Route path="/w/:slug" element={<PageViewPage />} />
          <Route path="/w/:id/edit" element={<PageEditorPage />} />
          <Route path="/t" element={<TagIndexPage />} />
          <Route path="/t/:tag" element={<TagPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/users" element={can('admin') ? <UsersPage /> : <Navigate to="/" replace />} />
          <Route
            path="/categories"
            element={can('admin') ? <CategoriesPage /> : <Navigate to="/" replace />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}

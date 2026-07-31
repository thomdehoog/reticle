import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { useAuth } from './auth/AuthContext'
import { CategoryPage } from './pages/CategoryPage'
import { GuideEditorPage } from './pages/GuideEditorPage'
import { GuideViewPage } from './pages/GuideViewPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { SearchPage } from './pages/SearchPage'
import { UsersPage } from './pages/UsersPage'

/**
 * Reticle has no public surface, so an unauthenticated visitor gets the login
 * screen whatever the URL says. Keeping the requested path in the address bar
 * means that after logging in, the very same render tree resolves the page they
 * originally asked for — no redirect dance, no "returnTo" parameter to leak.
 */
export function App() {
  const { status, can } = useAuth()

  if (status === 'checking') {
    return <div className="spinner">Loading Reticle…</div>
  }

  if (status === 'anonymous') {
    return <LoginPage />
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/c/:slug" element={<CategoryPage />} />
        <Route path="/g/:slug" element={<GuideViewPage />} />
        <Route path="/g/:id/edit" element={<GuideEditorPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/users" element={can('admin') ? <UsersPage /> : <Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  )
}

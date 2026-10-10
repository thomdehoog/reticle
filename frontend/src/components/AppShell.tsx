import { Link, Outlet, useNavigate, useRouterState } from '@tanstack/react-router'
import { useEffect, useState, type FormEvent } from 'react'

import { useLogout, useSession } from '../auth/session'
import { IconPlus, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

/**
 * The search term in the address bar, or '' anywhere but the search page.
 * Read loosely from the location because the header sits above every route.
 */
function useCurrentSearchTerm(): string {
  return useRouterState({
    select: (state) => {
      const term = (state.location.search as { q?: unknown }).q
      return typeof term === 'string' ? term : ''
    },
  })
}

/** The frame around every signed-in screen; the matched route renders in `<Outlet />`. */
export function AppShell() {
  const { user, can } = useSession()
  const logout = useLogout()
  const navigate = useNavigate()
  const currentTerm = useCurrentSearchTerm()
  const [query, setQuery] = useState(currentTerm)
  const [creating, setCreating] = useState(false)

  /* Keeps the box honest when the term changes without it — a reload, or the
     back button from one search to the previous one. */
  useEffect(() => setQuery(currentTerm), [currentTerm])

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed !== '') void navigate({ to: '/search', search: { q: trimmed } })
  }

  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          <ReticleMark />
          Reticle
          <span className="app__brand-sub">ZMB</span>
        </Link>

        <form className="searchbar" role="search" onSubmit={onSearch}>
          <label className="visually-hidden" htmlFor="global-search">
            Search guides
          </label>
          <input
            id="global-search"
            type="search"
            placeholder="Search guides…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </form>

        <div className="app__spacer" />

        {can('author') && (
          <button className="button button--primary" type="button" onClick={() => setCreating(true)}>
            <IconPlus />
            New guide
          </button>
        )}

        {can('admin') && (
          <Link className="button" to="/users">
            People
          </Link>
        )}

        <Link className="app__user" to="/account" title="Your account">
          <span className="avatar" aria-hidden="true">
            {initials(user?.displayName ?? '')}
          </span>
          <span>{user?.displayName}</span>
        </Link>

        <button className="button" type="button" onClick={() => logout.mutate()}>
          Sign out
        </button>
      </header>

      <main className="app__main">
        <Outlet />
      </main>

      {creating && <NewGuideDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

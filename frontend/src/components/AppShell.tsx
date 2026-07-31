import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'
import { IconPlus, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout, can } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed !== '') navigate(`/search?q=${encodeURIComponent(trimmed)}`)
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

        <div className="app__user">
          <span className="avatar" aria-hidden="true">
            {initials(user?.displayName ?? '')}
          </span>
          <span>{user?.displayName}</span>
        </div>

        <button className="button" type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>

      <main className="app__main">{children}</main>

      {creating && <NewGuideDialog onClose={() => setCreating(false)} />}
    </div>
  )
}

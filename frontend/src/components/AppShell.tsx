import { useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, useNavigate } from 'react-router'

import { useAuth } from '../auth/AuthContext'
import { IconPlus, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'
import { NewPageDialog } from './NewPageDialog'

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

/**
 * The frame every screen sits in.
 *
 * Navigation and actions are kept apart on purpose: the left group is places
 * you can go, the right group is things you can make. Tags and the wiki are in
 * the left group because at ZMB they are the two indexes people navigate by,
 * and neither was reachable without already being on a guide that linked to it.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout, can, organisation } = useAuth()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [creatingGuide, setCreatingGuide] = useState(false)
  const [creatingPage, setCreatingPage] = useState(false)

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
          {organisation && <span className="app__brand-sub">{organisation.shortName}</span>}
        </Link>

        <nav className="app__nav" aria-label="Sections">
          <NavLink className="app__nav-link" to="/w">
            Wiki
          </NavLink>
          <NavLink className="app__nav-link" to="/t">
            Tags
          </NavLink>
          {can('admin') && (
            <>
              <NavLink className="app__nav-link" to="/categories">
                Categories
              </NavLink>
              <NavLink className="app__nav-link" to="/users">
                People
              </NavLink>
            </>
          )}
        </nav>

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
          <>
            <button
              className="button button--primary"
              type="button"
              onClick={() => setCreatingGuide(true)}
            >
              <IconPlus />
              New guide
            </button>
            <button className="button" type="button" onClick={() => setCreatingPage(true)}>
              <IconPlus />
              New page
            </button>
          </>
        )}

        <Link className="app__user" to="/account" title="Your account">
          <span className="avatar" aria-hidden="true">
            {initials(user?.displayName ?? '')}
          </span>
          <span>{user?.displayName}</span>
        </Link>

        <button className="button" type="button" onClick={() => void logout()}>
          Sign out
        </button>
      </header>

      <main className="app__main">{children}</main>

      {creatingGuide && <NewGuideDialog onClose={() => setCreatingGuide(false)} />}
      {creatingPage && <NewPageDialog onClose={() => setCreatingPage(false)} />}
    </div>
  )
}

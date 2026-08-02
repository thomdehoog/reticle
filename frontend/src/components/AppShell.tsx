/**
 * The frame that stays put while the middle changes.
 *
 * The header, the search box, the sign-out button and the side navigation are the
 * same on every screen, so they are drawn once here and the actual page is
 * dropped into the middle. Moving between guides swaps only the middle, which is
 * why navigation feels instant and why the scroll position of the sidebar is not
 * thrown away every time you click something.
 *
 * Navigation and actions are kept apart on purpose: the left group is places you
 * can go, the right group is things you can make. Tags and the wiki are in the
 * left group because at ZMB they are the two indexes people navigate by, and
 * neither is reachable without already being on a guide that links to it.
 *
 * On a phone all of that collapses behind one button. Laid out in a row it wraps
 * to four rows and takes 233px of a 568px screen before the page has begun —
 * permanently, on every screen, for somebody holding the phone in one hand at an
 * instrument who wants step 1. Everything but the brand and the search box moves
 * into a menu, and the header stays one row tall.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router'

import { useAuth } from '../auth/AuthContext'
import { IconMenu, IconPlus, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'
import { NewPageDialog } from './NewPageDialog'

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout, can, organisation } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [query, setQuery] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [creatingGuide, setCreatingGuide] = useState(false)
  const [creatingPage, setCreatingPage] = useState(false)

  // Arriving somewhere is the end of using the menu. Left open, it covers the
  // screen the reader just asked for.
  useEffect(() => setMenuOpen(false), [pathname])

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

        <button
          className="app__menu-toggle"
          type="button"
          aria-label="Menu"
          aria-expanded={menuOpen}
          aria-controls="app-menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <IconMenu size={20} />
        </button>

        {/*
          One set of links for both layouts. `display: contents` dissolves this
          wrapper on a wide screen, so its children sit in the header row exactly
          as they would without it; on a phone the same wrapper is the panel the
          menu button opens. A second copy of the navigation for small screens
          would be a second thing to keep in step, and the copy nobody is looking
          at is the one that rots.
        */}
        <div className={`app__drawer${menuOpen ? ' app__drawer--open' : ''}`} id="app-menu">
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
        </div>
      </header>

      <main className="app__main">{children}</main>

      {creatingGuide && <NewGuideDialog onClose={() => setCreatingGuide(false)} />}
      {creatingPage && <NewPageDialog onClose={() => setCreatingPage(false)} />}
    </div>
  )
}

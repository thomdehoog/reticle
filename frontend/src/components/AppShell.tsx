/**
 * The frame that stays put while the middle changes.
 *
 * The header, the search box and the account controls are the same on every
 * screen, so they are drawn once here and the actual page is dropped into the
 * middle. Moving between guides swaps only the middle, which is why navigation
 * feels instant.
 *
 * The bar carries what a reader uses and nothing else: the brand, the wiki, the
 * tags, and search. The two administrator screens, the account, signing out and
 * the two ways to create something sit behind controls that have to be opened
 * first — eleven items across the top of every page is eleven things to read
 * past on the way to a procedure.
 *
 * On a phone even that is too much furniture. Laid out in a row the header
 * wrapped to four rows and took 233px of a 568px screen before the page had
 * begun, on every screen, for somebody holding the phone in one hand at an
 * instrument. Below the breakpoint the bar is brand, search and one button, and
 * everything else is in the sheet that button opens.
 */

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Link, NavLink, useLocation, useNavigate } from 'react-router'

import { useAuth } from '../auth/AuthContext'
import { IconMenu, IconPlus, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'
import { NewPageDialog } from './NewPageDialog'
import { Modal } from './ui'

/** The width below which the header is a brand, a search box and a button. */
const PHONE_WIDTH = '(max-width: 860px)'

function subscribeToWidth(onChange: () => void) {
  const query = window.matchMedia(PHONE_WIDTH)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/**
 * Whether the header is in its phone layout.
 *
 * The stylesheet knows this already, but the component has to know it too,
 * because what the button opens differs in kind between the two. On a wide
 * screen it is a small panel hanging off a control and the page behind it stays
 * usable. On a phone it is a sheet that covers the screen, and a sheet that
 * covers the screen has to hold the keyboard as well, or Tab walks off into a
 * guide the reader can no longer see.
 *
 * `useSyncExternalStore` reads the query during render, so there is no first
 * paint in the wrong layout and no effect setting state to correct one.
 */
function usePhoneLayout(): boolean {
  return useSyncExternalStore(
    subscribeToWidth,
    () => window.matchMedia(PHONE_WIDTH).matches,
    () => false,
  )
}

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  const first = parts[0][0]
  const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
  return (first + last).toUpperCase()
}

/** Which of the header's controls is showing its contents; one at a time. */
type MenuName = 'new' | 'account' | 'sheet'

/**
 * A header control that opens a panel beneath itself.
 *
 * Deliberately not `role="menu"`: that role promises arrow-key navigation
 * between the items, and these panels hold ordinary links and buttons that Tab
 * already reaches in the right order. Escape closes and hands focus back to the
 * button, because leaving focus on a node that has just been removed drops the
 * next keystroke on `<body>`, at the top of the page.
 */
function HeaderMenu({
  id,
  trigger,
  triggerClassName,
  label,
  open,
  onOpen,
  onClose,
  children,
}: {
  id: string
  trigger: ReactNode
  triggerClassName: string
  /** What a screen reader announces, for a button whose face is a picture. */
  label?: string
  open: boolean
  onOpen: () => void
  onClose: () => void
  children: ReactNode
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return

    /* Anywhere outside the control is somebody asking for the panel to go away. */
    function dismiss(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) onClose()
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      onClose()
      buttonRef.current?.focus()
    }

    document.addEventListener('mousedown', dismiss)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', dismiss)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, onClose])

  return (
    <div className="header-menu" ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={triggerClassName}
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => (open ? onClose() : onOpen())}
      >
        {trigger}
      </button>
      {open && (
        <div className="header-menu__panel" id={id}>
          {children}
        </div>
      )}
    </div>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout, can, organisation } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const phone = usePhoneLayout()
  const [query, setQuery] = useState('')
  const [creatingGuide, setCreatingGuide] = useState(false)
  const [creatingPage, setCreatingPage] = useState(false)

  /**
   * A menu belongs to the screen it was opened on.
   *
   * Recording which path that was closes every menu as a consequence of
   * rendering the new screen. The alternative — an effect watching the path and
   * setting the state back — runs after the screen the reader asked for has
   * already been painted with the menu still sitting over it.
   */
  const [opened, setOpened] = useState<{ menu: MenuName; path: string } | null>(null)
  const openMenu = opened?.path === pathname ? opened.menu : null
  const open = (menu: MenuName) => setOpened({ menu, path: pathname })
  const close = () => setOpened(null)

  function onSearch(event: FormEvent) {
    event.preventDefault()
    const trimmed = query.trim()
    if (trimmed !== '') navigate(`/search?q=${encodeURIComponent(trimmed)}`)
  }

  const displayName = user?.displayName ?? ''

  /* The same entries in the wide screen's account panel and in the phone's
     sheet, written once so neither can quietly lose one the other keeps. */
  const accountItems = (
    <>
      <Link className="menu-item" to="/account">
        Your account
      </Link>
      {can('admin') && (
        <>
          <Link className="menu-item" to="/categories">
            Categories
          </Link>
          <Link className="menu-item" to="/users">
            People
          </Link>
        </>
      )}
      <button className="menu-item" type="button" onClick={() => void logout()}>
        Sign out
      </button>
    </>
  )

  return (
    <div className="app">
      <header className="app__header">
        <Link to="/" className="app__brand">
          <ReticleMark />
          Reticle
          {organisation && <span className="app__brand-sub">{organisation.shortName}</span>}
        </Link>

        {!phone && (
          <nav className="app__nav" aria-label="Sections">
            <NavLink className="app__nav-link" to="/w">
              Wiki
            </NavLink>
            <NavLink className="app__nav-link" to="/t">
              Tags
            </NavLink>
          </nav>
        )}

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

        {!phone && can('author') && (
          <HeaderMenu
            id="new-menu"
            triggerClassName="button button--primary"
            trigger={
              <>
                <IconPlus />
                New
              </>
            }
            open={openMenu === 'new'}
            onOpen={() => open('new')}
            onClose={close}
          >
            <button
              className="menu-item"
              type="button"
              onClick={() => {
                close()
                setCreatingGuide(true)
              }}
            >
              Guide
            </button>
            <button
              className="menu-item"
              type="button"
              onClick={() => {
                close()
                setCreatingPage(true)
              }}
            >
              Page
            </button>
          </HeaderMenu>
        )}

        {!phone && (
          <HeaderMenu
            id="account-menu"
            triggerClassName="app__user"
            label={`Account: ${displayName}`}
            trigger={
              <span className="avatar" aria-hidden="true">
                {initials(displayName)}
              </span>
            }
            open={openMenu === 'account'}
            onOpen={() => open('account')}
            onClose={close}
          >
            <span className="menu-name">{displayName}</span>
            {accountItems}
          </HeaderMenu>
        )}

        {phone && (
          <button
            className="app__menu-toggle"
            type="button"
            aria-expanded={openMenu === 'sheet'}
            aria-controls="app-menu"
            onClick={() => (openMenu === 'sheet' ? close() : open('sheet'))}
          >
            <IconMenu size={20} />
            Menu
          </button>
        )}
      </header>

      <main className="app__main">{children}</main>

      {phone && openMenu === 'sheet' && (
        <Modal id="app-menu" title="Menu" onClose={close}>
          <nav className="menu-sheet" aria-label="Everywhere else">
            <Link className="menu-item" to="/w">
              Wiki
            </Link>
            <Link className="menu-item" to="/t">
              Tags
            </Link>
            {can('author') && (
              <>
                <button
                  className="menu-item"
                  type="button"
                  onClick={() => {
                    close()
                    setCreatingGuide(true)
                  }}
                >
                  New guide
                </button>
                <button
                  className="menu-item"
                  type="button"
                  onClick={() => {
                    close()
                    setCreatingPage(true)
                  }}
                >
                  New page
                </button>
              </>
            )}
            {accountItems}
          </nav>
        </Modal>
      )}

      {creatingGuide && <NewGuideDialog onClose={() => setCreatingGuide(false)} />}
      {creatingPage && <NewPageDialog onClose={() => setCreatingPage(false)} />}
    </div>
  )
}

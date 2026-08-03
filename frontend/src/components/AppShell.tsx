/**
 * The frame that stays put while the middle changes.
 *
 * Navigation, search and the account are the same on every screen, so they are
 * drawn once here and the actual page is dropped into the middle. Moving
 * between guides swaps only the middle, which is why navigation feels instant.
 *
 * On a wide screen the frame is a rail down the left and a bar above the
 * content that does one job. The sections used to run across the top, and that
 * is exactly the shape of the intranet page Reticle replaces: a strip of
 * headings above the material, with no room in it for the material's own
 * structure, so the strip stays the same wherever you go and answers neither
 * "where am I" nor "what else is at this level". Standing the same list on its
 * side gives it as many rows as a facility has sections, room for the current
 * one to be marked, and room for the level below it — and it empties the top
 * bar down to search and the one button that makes something. Everything that
 * used to be up there is in the rail: the brand, the facility, the wiki, the
 * tags, and the person signed in.
 *
 * On a phone even one strip is too much furniture. Laid out in a row the old
 * header wrapped to four rows and took 233px of a 568px screen before the page
 * had begun, on every screen, for somebody holding the phone in one hand at an
 * instrument. Below the breakpoint the bar is brand, search and one button, the
 * rail is not rendered at all, and the rail's contents are in the sheet that
 * button opens.
 */

import {
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
  type FormEvent,
  type ReactNode,
} from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { useAuth } from '../auth/AuthContext'
import { IconBook, IconHome, IconMenu, IconPlus, IconTag, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'
import { NewPageDialog } from './NewPageDialog'
import { RailPlaces, SideRail } from './SideRail'
import { Modal } from './ui'

/** The width below which the header is a brand, a search box and a button. */
const PHONE_WIDTH = '(max-width: 860px)'

function subscribeToWidth(onChange: () => void) {
  const query = window.matchMedia(PHONE_WIDTH)
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

/**
 * Whether the shell is in its phone layout.
 *
 * The stylesheet knows this already, but the component has to know it too, for
 * two reasons. The rail must not be built at all below the breakpoint — hiding
 * a column of links in CSS still leaves them in the Tab order and in a screen
 * reader's list. And what the button opens differs in kind between the two: on
 * a wide screen it is a small panel hanging off a control and the page behind
 * it stays usable; on a phone it is a sheet that covers the screen, and a sheet
 * that covers the screen has to hold the keyboard as well, or Tab walks off
 * into a guide the reader can no longer see.
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

/** Which of the shell's controls is showing its contents; one at a time. */
type MenuName = 'new' | 'account' | 'sheet'

/**
 * A control that opens a panel beside itself.
 *
 * Deliberately not `role="menu"`: that role promises arrow-key navigation
 * between the items, and these panels hold ordinary links and buttons that Tab
 * already reaches in the right order. Escape closes and hands focus back to the
 * button, because leaving focus on a node that has just been removed drops the
 * next keystroke on `<body>`, at the top of the page.
 */
function HeaderMenu({
  id,
  className,
  trigger,
  triggerClassName,
  label,
  open,
  onOpen,
  onClose,
  children,
}: {
  id: string
  /** Modifier on the wrapper, which is what decides where the panel appears. */
  className?: string
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
    <div className={`header-menu${className ? ` ${className}` : ''}`} ref={rootRef}>
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

  /* The same entries in the rail's account panel and in the phone's sheet,
     written once so neither can quietly lose one the other keeps. */
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

  /* At the foot of the rail rather than in the bar: whose session this is is a
     question asked once a day, and it was taking a corner of every screen.

     A reader who is not signed in gets a way in rather than an empty avatar.
     Most people who open Reticle came to read a procedure and will never use
     this, so it stays where the account menu was rather than being promoted to
     something the reader has to get past. */
  const account = user ? (
    <HeaderMenu
      id="account-menu"
      className="header-menu--rail"
      triggerClassName="rail__me"
      label={`Account: ${displayName}`}
      trigger={
        <>
          <span className="avatar" aria-hidden="true">
            {initials(displayName)}
          </span>
          <span className="rail__me-name">{displayName}</span>
        </>
      }
      open={openMenu === 'account'}
      onOpen={() => open('account')}
      onClose={close}
    >
      {accountItems}
    </HeaderMenu>
  ) : (
    <Link className="rail__me" to="/login">
      <span className="rail__me-name">Sign in to edit</span>
    </Link>
  )

  /* The rail's own cell is one window tall, so the stylesheet paints the column
     behind it; `app--rail` is how it knows there is a rail to paint. */
  return (
    <div className={`app${phone ? '' : ' app--rail'}`}>
      {!phone && <SideRail account={account} />}

      <div className="app__column">
        <header className={`app__header${phone ? '' : ' app__header--desk'}`}>
          {phone && (
            <Link to="/" className="app__brand">
              <ReticleMark />
              Reticle
              {organisation && <span className="app__brand-sub">{organisation.shortName}</span>}
            </Link>
          )}

          <form className="searchbar" role="search" onSubmit={onSearch}>
            <label className="visually-hidden" htmlFor="global-search">
              Search guides
            </label>
            <input
              id="global-search"
              type="search"
              placeholder="Search"
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
      </div>

      {phone && openMenu === 'sheet' && (
        <Modal id="app-menu" title="Menu" onClose={close}>
          <nav className="menu-sheet" aria-label="Everywhere else">
            <Link className="menu-item" to="/">
              <IconHome size={17} />
              Home
            </Link>
            <Link className="menu-item" to="/w">
              <IconBook size={17} />
              Wiki
            </Link>
            <Link className="menu-item" to="/t">
              <IconTag size={17} />
              Tags
            </Link>

            {/* The same list the rail carries. A drawer that only offered the
                wiki and the tags left the categories reachable on a phone only
                by going back to the front page and starting again. */}
            <RailPlaces />

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
            {user ? (
              accountItems
            ) : (
              <Link className="menu-item" to="/login" onClick={close}>
                Sign in to edit
              </Link>
            )}
          </nav>
        </Modal>
      )}

      {creatingGuide && <NewGuideDialog onClose={() => setCreatingGuide(false)} />}
      {creatingPage && <NewPageDialog onClose={() => setCreatingPage(false)} />}
    </div>
  )
}

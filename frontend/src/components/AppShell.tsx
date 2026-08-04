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
 * used to be up there is in the rail: the brand, the facility, and the person
 * signed in.
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
import { IconMenu, ReticleMark } from './icons'
import { NewGuideDialog } from './NewGuideDialog'
import { NewPageDialog } from './NewPageDialog'
import { RailGroups, SideRail } from './SideRail'
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

/**
 * Scroll to whatever the address names after the `#`.
 *
 * The router handles a link to `/c/widefield#group-thunder` itself, changing the
 * URL without the jump a browser performs for a plain anchor — so the rail's
 * group links moved the address bar and nothing else. This puts the jump back.
 *
 * It retries for a few frames because the target usually does not exist yet.
 * Following a group from a guide navigates to the section, and the section's
 * groups are drawn only once its guides have arrived over the network; the URL
 * changes first. Retrying briefly is the difference between landing on the
 * group and landing at the top of the page.
 */
function useScrollToHash() {
  const { hash, key } = useLocation()

  useEffect(() => {
    if (!hash) return
    const id = decodeURIComponent(hash.slice(1))
    let frames = 0
    let raf = 0

    const look = () => {
      const target = document.getElementById(id)
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' })
        return
      }
      /* About a second at 60fps. Long enough for a listing to arrive, short
         enough that it is not still scrolling the page under a reader who gave
         up waiting and started reading. */
      if (frames++ < 60) raf = requestAnimationFrame(look)
    }

    raf = requestAnimationFrame(look)
    return () => cancelAnimationFrame(raf)
    /* `key` is in here so that following the same group twice scrolls twice:
       the hash has not changed, but the reader asked again. */
  }, [hash, key])
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
  useScrollToHash()
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
     written once so neither can quietly lose one the other keeps.

     Writing lives here rather than in the bar. The bar is what every reader
     looks at on every screen, and almost nobody who opens Reticle is about to
     write a guide — a permanent button for the rare case, in the busiest corner
     of the frame, charges every reader for an author's convenience. Behind the
     account it is two clicks for the person who wants it and nothing at all for
     everybody else, and it sits with the other things that are about you rather
     than about the material. */
  const accountItems = (
    <>
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

  /* One corner of the bar, holding whichever of the two applies: "Sign in" for
     somebody who has not, and who they are for somebody who has. It used to sit
     at the foot of the rail, which left the rail carrying two unrelated things
     — where you can go, and who you are — and left this corner meaning
     something different depending on your session. The rail is navigation now,
     top to bottom, and this corner is you. */
  const account = user && (
    <HeaderMenu
      id="account-menu"
      triggerClassName="app__me"
      label={`Account: ${displayName}`}
      trigger={
        <>
          <span className="avatar" aria-hidden="true">
            {initials(displayName)}
          </span>
          <span className="app__me-name">{displayName}</span>
        </>
      }
      open={openMenu === 'account'}
      onOpen={() => open('account')}
      onClose={close}
    >
      {accountItems}
    </HeaderMenu>
  )

  return (
    <div className={`app${phone ? '' : ' app--rail'}`}>
      {!phone && <SideRail />}

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

          {/* Top right, and always the same question: who is this. Signed in it
              is your name and the menu behind it; signed out it is the way to
              sign in. "New" used to have this corner — it is behind the account
              now, because the bar is on every screen every reader looks at and
              writing a guide is the rarest thing anybody does here. */}
          {!phone &&
            (user ? (
              account
            ) : (
              <Link className="button button--primary" to="/login">
                Sign in
              </Link>
            ))}

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
            {/* The same two areas the rail carries, Home among them. The drawer
                is the rail on a screen too narrow to hold one, so what one
                offers the other offers — a phone that kept an entry the desktop
                had dropped would be a second navigation model nobody decided
                on. */}
            <RailGroups />

            {/* Creating is in `accountItems` now, so the drawer gets it from
                there rather than keeping a second copy that has to be changed
                twice.

                On a phone the bar holds the brand, the search box and the one
                menu button, so the sign-in that sits in the bar on a wide
                screen has nowhere to be but in here. Same words either way. */}
            {user ? (
              accountItems
            ) : (
              <Link className="menu-item" to="/login" onClick={close}>
                Sign in
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

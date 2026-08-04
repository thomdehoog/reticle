import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import type { User } from '../domain/types'
import { createFakeServer } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { AppShell } from './AppShell'

const AUTHOR: User = {
  id: 'u-eva',
  email: 'eva@zmb.uzh.ch',
  displayName: 'Eva Meier',
  role: 'author',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

const VIEWER: User = { ...AUTHOR, id: 'u-anna', displayName: 'Anna Roth', role: 'viewer' }

function renderShell(user: User, route = '/') {
  const server = createFakeServer({ user })
  renderWithApp(
    <AppShell>
      <div>Content</div>
    </AppShell>,
    { route, fetchImpl: server.fetchImpl },
  )
  return server
}

/**
 * Put the header in its phone layout for one test.
 *
 * The component asks a media query which of its two shapes it is in, and jsdom
 * answers "no" to everything, so the wide layout is what every other test here
 * renders. This replaces the answer for the narrow query only.
 */
function pretendPhone() {
  const real = window.matchMedia
  window.matchMedia = ((media: string) =>
    ({
      media,
      matches: media.includes('max-width: 860px'),
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList) as typeof window.matchMedia
  return () => {
    window.matchMedia = real
  }
}

describe('AppShell', () => {
  it('reaches the front page from anywhere', async () => {
    renderShell(VIEWER)

    expect(await screen.findByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
  })

  /* The two institute-wide indexes were dropped from the rail: both answer
     "everything, everywhere", which is the one question the rail is not for.
     Asserted rather than assumed, because the drawer below is built from the
     same list and a link put back in one place belongs in both. */
  it('keeps the institute-wide indexes out of the rail', async () => {
    renderShell(VIEWER)

    await screen.findByRole('link', { name: 'Home' })
    expect(screen.queryByRole('link', { name: 'Wiki' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Tags' })).not.toBeInTheDocument()
  })

  /* The two administrator screens are not primary navigation — every viewer was
     being shown two links they can do nothing with — so they sit with the
     account, which is the other thing about you rather than about the material. */
  it('offers both admin screens the account pages promise, behind the account', async () => {
    const user = userEvent.setup()
    renderShell({ ...AUTHOR, role: 'admin' })

    await user.click(await screen.findByRole('button', { name: /^Account:/ }))
    const account = screen.getByRole('link', { name: 'People' }).closest('div')!

    expect(within(account).getByRole('link', { name: 'People' })).toHaveAttribute('href', '/users')
    expect(within(account).getByRole('link', { name: 'Categories' })).toHaveAttribute(
      'href',
      '/categories',
    )
  })

  it('keeps the admin screens out of a non-admin’s account menu', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    await user.click(await screen.findByRole('button', { name: /^Account:/ }))
    expect(screen.getByRole('link', { name: 'Your account' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'People' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Categories' })).not.toBeInTheDocument()
  })

  it('offers a viewer no way to create anything', async () => {
    renderShell(VIEWER)

    await screen.findByRole('link', { name: 'Home' })
    expect(screen.queryByRole('button', { name: 'New' })).not.toBeInTheDocument()
  })

  it('opens one dialog at a time', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    await user.click(await screen.findByRole('button', { name: 'New' }))
    await user.click(screen.getByRole('button', { name: 'Page' }))

    expect(screen.getByRole('dialog', { name: 'New page' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'New guide' })).not.toBeInTheDocument()
  })

  it('marks the front page when that is what is open', async () => {
    renderShell(VIEWER)

    /* Marked the way every other step of the path is, rather than by a router
       class of its own: the stylesheet turns it into weight and a bar. */
    expect(await screen.findByRole('link', { name: 'Home' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })

  it('leaves it unmarked while something else is being read', async () => {
    renderShell(VIEWER, '/w/immersion-oil')

    expect(await screen.findByRole('link', { name: 'Home' })).not.toHaveAttribute('aria-current')
  })
})

/**
 * The panels the header opens.
 *
 * A control that opens something has to say that it did, has to say what it
 * opened, and has to give the keyboard back when it closes — none of which is
 * visible from a screenshot, and all of which is the difference between the
 * menu being usable without a mouse and not.
 */
describe('AppShell menus', () => {
  it('says whether the account panel is open, and what it opens', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    const trigger = await screen.findByRole('button', { name: /^Account:/ })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')

    const panel = document.getElementById(trigger.getAttribute('aria-controls')!)
    expect(panel).toContainElement(screen.getByRole('link', { name: 'Your account' }))
  })

  it('closes the panel on Escape and hands the keyboard back', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    const trigger = await screen.findByRole('button', { name: /^Account:/ })
    await user.click(trigger)
    expect(screen.getByRole('link', { name: 'Your account' })).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('link', { name: 'Your account' })).not.toBeInTheDocument()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    /* Not `document.body`: the next Tab would start again at the top of the
       page, several screens away from what the author was doing. */
    expect(trigger).toHaveFocus()
  })

  it('shows one panel at a time', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    await user.click(await screen.findByRole('button', { name: 'New' }))
    expect(screen.getByRole('button', { name: 'Guide' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /^Account:/ }))

    expect(screen.queryByRole('button', { name: 'Guide' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Your account' })).toBeInTheDocument()
  })
})

describe('AppShell on a phone', () => {
  let restore = () => {}
  afterEach(() => restore())

  it('puts everything behind one button, in a sheet that holds the keyboard', async () => {
    restore = pretendPhone()
    const user = userEvent.setup()
    renderShell({ ...AUTHOR, role: 'admin' })

    /* The bar itself is the brand, the search box and this. */
    expect(screen.queryByRole('link', { name: 'Home' })).not.toBeInTheDocument()

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    const sheet = screen.getByRole('dialog', { name: 'Menu' })
    expect(sheet).toHaveAttribute('id', toggle.getAttribute('aria-controls'))
    for (const name of ['Home', 'Categories', 'People', 'Your account']) {
      expect(within(sheet).getByRole('link', { name })).toBeInTheDocument()
    }
    /* Dropped from the rail, so dropped here: the drawer is the rail on a
       narrow screen, and the two are not allowed to offer different places. */
    for (const name of ['Wiki', 'Tags']) {
      expect(within(sheet).queryByRole('link', { name })).not.toBeInTheDocument()
    }
    expect(within(sheet).getByRole('button', { name: 'New guide' })).toBeInTheDocument()
    expect(within(sheet).getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('closes the sheet on Escape and gives focus back to the button', async () => {
    restore = pretendPhone()
    const user = userEvent.setup()
    renderShell(AUTHOR)

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    await user.click(toggle)
    expect(screen.getByRole('dialog', { name: 'Menu' })).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(screen.queryByRole('dialog', { name: 'Menu' })).not.toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveFocus()
  })

  /**
   * Tab must not walk out of the sheet: it covers the guide, so anything it
   * reached behind would be focus landing somewhere the reader cannot see.
   */
  it('keeps Tab inside the sheet while it is open', async () => {
    restore = pretendPhone()
    const user = userEvent.setup()
    renderShell(VIEWER)

    await user.click(await screen.findByRole('button', { name: 'Menu' }))
    const sheet = screen.getByRole('dialog', { name: 'Menu' })

    for (let press = 0; press < 12; press++) {
      await user.tab()
      expect(sheet).toContainElement(document.activeElement as HTMLElement)
    }
  })
})

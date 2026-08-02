import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes, useNavigate } from 'react-router'

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

describe('AppShell', () => {
  it('reaches the wiki and the tag index from anywhere', async () => {
    renderShell(VIEWER)

    expect(await screen.findByRole('link', { name: 'Wiki' })).toHaveAttribute('href', '/w')
    expect(screen.getByRole('link', { name: 'Tags' })).toHaveAttribute('href', '/t')
  })

  it('offers both admin screens the account pages promise', async () => {
    renderShell({ ...AUTHOR, role: 'admin' })

    expect(await screen.findByRole('link', { name: 'People' })).toHaveAttribute('href', '/users')
    expect(screen.getByRole('link', { name: 'Categories' })).toHaveAttribute('href', '/categories')
  })

  it('keeps the admin screens out of a non-admin’s header', async () => {
    renderShell(AUTHOR)

    await screen.findByRole('link', { name: 'Wiki' })
    expect(screen.queryByRole('link', { name: 'People' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Categories' })).not.toBeInTheDocument()
  })

  it('offers a viewer neither of the two ways to create something', async () => {
    renderShell(VIEWER)

    await screen.findByRole('link', { name: 'Wiki' })
    expect(screen.queryByRole('button', { name: /New guide/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /New page/ })).not.toBeInTheDocument()
  })

  it('opens one dialog at a time', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    await user.click(await screen.findByRole('button', { name: /New page/ }))
    expect(screen.getByRole('dialog', { name: 'New page' })).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'New guide' })).not.toBeInTheDocument()
  })

  it('marks the section being read, for a reader who cannot see the styling', async () => {
    renderShell(VIEWER, '/w/immersion-oil')

    /* react-router adds `active` for the matching NavLink; the stylesheet turns
       that into weight and a rule rather than a shade of the header blue. */
    expect(await screen.findByRole('link', { name: 'Wiki' })).toHaveClass('active')
    expect(screen.getByRole('link', { name: 'Tags' })).not.toHaveClass('active')
  })
})

/**
 * On a phone everything but the brand and the search box lives behind one
 * button, so the state of that button is the state of the whole navigation.
 * The links are in the document either way — the stylesheet decides whether the
 * panel holding them is a header row or a drop-down — so what is worth asserting
 * is that the control says what it is doing and that the panel does not stay
 * open over the screen it just took the reader to.
 */
describe('AppShell menu', () => {
  it('says whether the menu is open', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('points the button at the panel it opens', async () => {
    renderShell(AUTHOR)

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    const controlled = toggle.getAttribute('aria-controls')
    expect(controlled).toBeTruthy()
    expect(document.getElementById(controlled as string)).toContainElement(
      screen.getByRole('link', { name: 'Wiki' }),
    )
  })

  it('gets out of the way when the page behind it is tapped', async () => {
    const user = userEvent.setup()
    renderShell(AUTHOR)

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(screen.getByText('Content'))
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })

  it('closes itself once it has taken the reader somewhere', async () => {
    const user = userEvent.setup()
    const server = createFakeServer({ user: AUTHOR })

    function GoToWiki() {
      const navigate = useNavigate()
      return (
        <button type="button" onClick={() => navigate('/w')}>
          Go to the wiki
        </button>
      )
    }

    renderWithApp(
      <AppShell>
        <Routes>
          <Route path="/" element={<GoToWiki />} />
          <Route path="/w" element={<div>Wiki index</div>} />
        </Routes>
      </AppShell>,
      { route: '/', fetchImpl: server.fetchImpl },
    )

    const toggle = await screen.findByRole('button', { name: 'Menu' })
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')

    await user.click(screen.getByRole('button', { name: 'Go to the wiki' }))

    expect(await screen.findByText('Wiki index')).toBeInTheDocument()
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
  })
})

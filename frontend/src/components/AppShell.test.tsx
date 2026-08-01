import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

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

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { User } from '../domain/types'
import { createFakeServer } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { UsersPage } from './UsersPage'

const ADMIN: User = {
  id: 'u-thom',
  email: 'thom.dehoog@zmb.uzh.ch',
  displayName: 'Thom de Hoog',
  role: 'admin',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

const COLLEAGUE: User = {
  id: 'u-eva',
  email: 'eva@zmb.uzh.ch',
  displayName: 'Eva Meier',
  role: 'author',
  isActive: true,
  createdAt: '2026-03-14T00:00:00Z',
}

function renderUsers(users: User[] = [ADMIN, COLLEAGUE]) {
  const server = createFakeServer({ users })
  renderWithApp(<UsersPage />, { route: '/users', fetchImpl: server.fetchImpl })
  return server
}

async function rowFor(name: string): Promise<HTMLElement> {
  const cell = await screen.findByRole('button', { name: `Rename ${name}` })
  return cell.closest('tr') as HTMLElement
}

describe('UsersPage', () => {
  it('shows when each account was added', async () => {
    renderUsers()

    const added = new Date(COLLEAGUE.createdAt).toLocaleDateString()
    expect(within(await rowFor('Eva Meier')).getByText(added)).toBeInTheDocument()
  })

  it('renames somebody without creating a second account for them', async () => {
    const server = renderUsers()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Rename Eva Meier' }))
    const field = screen.getByLabelText('Name for eva@zmb.uzh.ch')
    await user.clear(field)
    await user.type(field, 'Eva Meier-Roth')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(server.state.users.find((person) => person.id === 'u-eva')?.displayName).toBe(
        'Eva Meier-Roth',
      ),
    )
    expect(await screen.findByRole('button', { name: 'Rename Eva Meier-Roth' })).toBeInTheDocument()
  })

  it('abandons a rename on Escape', async () => {
    const server = renderUsers()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: 'Rename Eva Meier' }))
    await user.type(screen.getByLabelText('Name for eva@zmb.uzh.ch'), 'X')
    await user.keyboard('{Escape}')

    expect(screen.getByRole('button', { name: 'Rename Eva Meier' })).toBeInTheDocument()
    expect(server.state.users[1].displayName).toBe('Eva Meier')
  })

  it('deactivates a colleague rather than deleting them', async () => {
    const server = renderUsers()
    const user = userEvent.setup()

    await user.click(within(await rowFor('Eva Meier')).getByRole('button', { name: 'Deactivate' }))

    await waitFor(() => expect(server.state.users[1].isActive).toBe(false))
    /* Their name stays in the list, so a guide they wrote still has an author
       an administrator can look up. */
    expect(
      within(await rowFor('Eva Meier')).getByRole('button', { name: 'Reactivate' }),
    ).toBeInTheDocument()
  })

  it('reactivates a switched-off account', async () => {
    const server = renderUsers([ADMIN, { ...COLLEAGUE, isActive: false }])
    const user = userEvent.setup()

    await user.click(within(await rowFor('Eva Meier')).getByRole('button', { name: 'Reactivate' }))

    await waitFor(() => expect(server.state.users[1].isActive).toBe(true))
  })

  /* An admin who switches off their own account locks everyone out of the
     admin screens, and the server is the only place that could undo it. */
  it('refuses to let an admin switch off their own account', async () => {
    renderUsers()

    const row = await rowFor('Thom de Hoog')
    expect(within(row).getByRole('button', { name: 'Deactivate' })).toBeDisabled()
    expect(within(row).getByLabelText('Role for Thom de Hoog')).toBeDisabled()
  })

  it('changes a colleague’s role', async () => {
    const server = renderUsers()
    const user = userEvent.setup()

    await user.selectOptions(
      await screen.findByLabelText('Role for Eva Meier'),
      'admin',
    )

    await waitFor(() => expect(server.state.users[1].role).toBe('admin'))
  })
})

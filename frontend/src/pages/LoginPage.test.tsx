import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { useAuth } from '../auth/AuthContext'
import { createFakeServer } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { LoginPage } from './LoginPage'

function SessionProbe() {
  const { user } = useAuth()
  return <div data-testid="session">{user ? user.displayName : 'signed out'}</div>
}

describe('LoginPage', () => {
  it('signs a ZMB user in with correct credentials', async () => {
    const server = createFakeServer()
    server.signOut()
    const user = userEvent.setup()

    renderWithApp(
      <>
        <LoginPage />
        <SessionProbe />
      </>,
      { fetchImpl: server.fetchImpl },
    )

    await waitFor(() => expect(screen.getByTestId('session')).toHaveTextContent('signed out'))

    await user.type(screen.getByLabelText('Email'), 'thom.dehoog@zmb.uzh.ch')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByTestId('session')).toHaveTextContent('Thom de Hoog'))
  })

  it('reports a rejected sign-in without revealing whether the account exists', async () => {
    const server = createFakeServer()
    server.signOut()
    const user = userEvent.setup()

    renderWithApp(<LoginPage />, { fetchImpl: server.fetchImpl })

    await user.type(screen.getByLabelText('Email'), 'nobody@example.org')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Email or password is incorrect.')
  })

  it('clears the password field after a failed attempt', async () => {
    const server = createFakeServer()
    server.signOut()
    const user = userEvent.setup()

    renderWithApp(<LoginPage />, { fetchImpl: server.fetchImpl })

    await user.type(screen.getByLabelText('Email'), 'thom.dehoog@zmb.uzh.ch')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await screen.findByRole('alert')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })
})

/**
 * What the application does when it cannot tell whether you are signed in.
 *
 * "Not signed in" and "could not ask" arrive at the same place in the code and
 * mean opposite things. Treating them alike signed a reader out because the
 * server was briefly busy — and a whole institute behind one address shares the
 * rate limiter's budget, so briefly busy is not hypothetical.
 */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import { App } from '../App'
import { AuthProvider } from './AuthContext'

/** A transport whose `/auth/me` fails the way the argument is about. */
function serverThat(status: number, code: string): typeof fetch {
  return (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/config')) {
      return new Response(JSON.stringify({ organisation: { name: 'ZMB', shortName: 'ZMB', url: null, tagline: null, heroImageUrl: null } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response(JSON.stringify({ error: { code, message: 'no' } }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
}

function renderApp(fetchImpl: typeof fetch) {
  return render(
    <MemoryRouter>
      <AuthProvider fetchImpl={fetchImpl}>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('deciding whether somebody is signed in', () => {
  it('shows the site, not a login form, when the server says they are not', async () => {
    /* Reading is public. Somebody who arrives without a session came to follow
       a procedure, and the sign-in is an offer at the foot of the rail rather
       than a gate across the front of the site. */
    renderApp(serverThat(401, 'not_authenticated'))

    expect(await screen.findByText(/sign in to edit/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument()
  })

  it('does not sign anybody out because the server was busy', async () => {
    /* The defect this file exists for: a 429 at page load emptied the session
       and dropped the reader on the login screen with no explanation. */
    renderApp(serverThat(429, 'rate_limited'))

    expect(await screen.findByText(/cannot be reached/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
  })

  it('does not sign anybody out because the server failed', async () => {
    renderApp(serverThat(500, 'internal_error'))

    expect(await screen.findByText(/cannot be reached/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument()
  })
})

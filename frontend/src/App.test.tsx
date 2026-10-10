/**
 * The assembled application: the session gate, the route table and its guards.
 *
 * These go through `renderApp`, so every one of them is the shipping wiring —
 * real client, real router, real query cache — against the in-memory server.
 */

import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { authKeys } from './auth/session'
import { createFakeServer, guideFixture, userFixture } from './test/fakeServer'
import { renderApp } from './test/harness'

const VIEWER = userFixture({
  id: 'u-vera',
  email: 'vera@zmb.uzh.ch',
  displayName: 'Vera Viewer',
  role: 'viewer',
})

const AUTHOR = userFixture({
  id: 'u-anna',
  email: 'anna@zmb.uzh.ch',
  displayName: 'Anna Author',
  role: 'author',
})

const PUBLISHED = guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1 })

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText('Email'), 'someone@zmb.uzh.ch')
  await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('signing in', () => {
  it('shows the login screen at the URL that was asked for, and lands there afterwards', async () => {
    const server = createFakeServer({ guides: [PUBLISHED] })
    server.signOut()
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')

    await signIn(user)

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
  })

  it('asks nothing of the server but who is there until someone has signed in', async () => {
    const server = createFakeServer()
    server.signOut()
    renderApp({ route: '/users', server })

    await screen.findByRole('button', { name: 'Sign in' })
    expect(server.requests.map((request) => request.path)).toEqual(['/auth/me'])
  })
})

describe('losing the session', () => {
  it('drops back to the login screen when any request is answered 401', async () => {
    const server = createFakeServer({ guides: [PUBLISHED] })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/', server })

    await user.click(await screen.findByRole('link', { name: /Light Microscopy/ }))
    await screen.findByText('Confocal startup')

    server.signOut()
    await user.click(screen.getByRole('link', { name: /Confocal startup/ }))

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    /* The address stays put, so signing in again resumes where they were going. */
    expect(location()).toBe('/g/confocal-startup')

    /* And it stays dropped: nothing keeps retrying against a dead session. */
    const settled = server.requests.length
    await new Promise((resolve) => setTimeout(resolve, 150))
    expect(server.requests.length).toBe(settled)
  })

  it('signs out on request even when the server cannot be told', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderApp({ route: '/', server })

    await screen.findByRole('heading', { name: 'Guides' })
    server.signOut()
    await user.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows the next person nothing the last one loaded', async () => {
    const draft = guideFixture({ title: 'Unannounced instrument' })
    const server = createFakeServer({ guides: [draft], users: [userFixture(), VIEWER] })
    const user = userEvent.setup()
    const { app } = renderApp({ route: '/', server })

    /* The admin's home page lists their own draft. */
    expect(await screen.findByText('Unannounced instrument')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('button', { name: 'Sign in' })

    /* Nothing but the (empty) session survives in the cache. */
    const cached = app.queryClient.getQueryCache().getAll()
    expect(cached.map((query) => query.queryKey)).toEqual([authKeys.me()])

    server.state.user = VIEWER
    await signIn(user)

    expect(await screen.findByText('Vera Viewer')).toBeInTheDocument()
    await screen.findByRole('heading', { name: 'Guides' })
    expect(screen.queryByText('Unannounced instrument')).not.toBeInTheDocument()
  })

  it('re-runs the role guards for the next person on the same URL', async () => {
    const server = createFakeServer({ users: [userFixture(), VIEWER] })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/users', server })

    expect(await screen.findByRole('heading', { name: 'People' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    server.state.user = VIEWER
    await signIn(user)

    await screen.findByRole('heading', { name: 'Guides' })
    expect(location()).toBe('/')
    expect(screen.queryByRole('heading', { name: 'People' })).not.toBeInTheDocument()
  })
})

describe('routes', () => {
  it('sends an unknown address home', async () => {
    const server = createFakeServer()
    const { location } = renderApp({ route: '/no/such/place', server })

    expect(await screen.findByRole('heading', { name: 'Guides' })).toBeInTheDocument()
    expect(location()).toBe('/')
  })

  it('keeps the people page to admins', async () => {
    const server = createFakeServer({ user: AUTHOR })
    const { location } = renderApp({ route: '/users', server })

    expect(await screen.findByRole('heading', { name: 'Guides' })).toBeInTheDocument()
    expect(location()).toBe('/')
    expect(server.count('GET', '/users')).toBe(0)
    expect(screen.queryByRole('link', { name: 'People' })).not.toBeInTheDocument()
  })

  it('lists people for an admin and changes a role', async () => {
    const server = createFakeServer({ users: [userFixture(), AUTHOR] })
    const user = userEvent.setup()
    renderApp({ route: '/users', server })

    const row = (await screen.findByText('Anna Author')).closest('tr') as HTMLElement
    const select = row.querySelector('select') as HTMLSelectElement
    expect(select).toHaveValue('author')

    await user.selectOptions(select, 'admin')

    await waitFor(() => expect(server.state.users[1].role).toBe('admin'))
    /* The list is re-read after the change rather than patched by hand. */
    await waitFor(() => expect(server.count('GET', '/users')).toBe(2))
    expect(select).toHaveValue('admin')
  })

  it.each(['/g/g-confocal/edit', '/w/p-objectives/edit'])(
    'keeps the editor at %s to authors',
    async (route) => {
      const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
      const { location } = renderApp({ route, server })

      expect(await screen.findByRole('heading', { name: 'Guides' })).toBeInTheDocument()
      expect(location()).toBe('/')
    },
  )

  it('shows a not-found screen in place for a guide that does not exist', async () => {
    const server = createFakeServer()
    const { location } = renderApp({ route: '/g/never-written', server })

    expect(await screen.findByText(/There is nothing here/)).toBeInTheDocument()
    expect(location()).toBe('/g/never-written')
  })

  it('does not let a viewer tell a draft from a guide that does not exist', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByText(/There is nothing here/)).toBeInTheDocument()
    expect(screen.queryByText('Confocal startup')).not.toBeInTheDocument()
  })

  it('searches from the header, with the term as plain text in the URL', async () => {
    const server = createFakeServer({ guides: [PUBLISHED] })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/', server })

    await user.type(await screen.findByLabelText('Search guides and wiki pages'), 'confocal 488{Enter}')

    expect(await screen.findByText('Results for “confocal 488”')).toBeInTheDocument()
    expect(location()).toBe('/search?q=confocal+488')
  })

  it('creates a guide from the header and opens it in the editor', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/', server })

    await user.click(await screen.findByRole('button', { name: 'New guide' }))
    await user.type(screen.getByLabelText('Title'), 'Aligning the Stellaris')
    await user.selectOptions(screen.getByLabelText('Category'), 'Light Microscopy')
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    expect(await screen.findByDisplayValue('Aligning the Stellaris')).toBeInTheDocument()
    expect(location()).toBe('/g/g-new-1/edit')

    /* The server creates a guide with no steps; the editor still opens on one
       to write in, and does not count showing it as a change worth saving. */
    expect(server.state.guides[1].steps).toHaveLength(0)
    expect(screen.getByPlaceholderText('Step 1 title (optional)')).toBeInTheDocument()
    await new Promise((resolve) => setTimeout(resolve, 1500))
    expect(server.requests.filter((request) => request.method === 'PUT')).toHaveLength(0)

    await user.type(screen.getByPlaceholderText('Describe what to do…'), 'Open the shutter.')
    await waitFor(() => expect(server.state.guides[1].steps).toHaveLength(1), { timeout: 4000 })
    expect(server.state.guides[1].steps[0].bullets[0].text).toBe('Open the shutter.')
  })
})

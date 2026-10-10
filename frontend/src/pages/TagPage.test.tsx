import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { createFakeServer, guideFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })

const published = (overrides: Parameters<typeof guideFixture>[0] = {}) =>
  guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1, ...overrides })

describe('TagPage', () => {
  it('gathers every guide carrying the tag, whichever category it lives in', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [
        published({ id: 'g1', slug: 'one', title: 'Navigator', categoryId: 'c-a', tags: ['las-x'] }),
        published({ id: 'g2', slug: 'two', title: 'Lightning', categoryId: 'c-b', tags: ['las-x'] }),
        published({ id: 'g3', slug: 'three', title: 'ZEN basics', tags: ['zen'] }),
      ],
    })
    renderApp({ route: '/t/las-x', server })

    expect(await screen.findByText('2 guides carry this tag.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Navigator/ })).toHaveAttribute('href', '/g/one')
    expect(screen.getByRole('link', { name: /Lightning/ })).toBeInTheDocument()
    expect(screen.queryByText('ZEN basics')).not.toBeInTheDocument()
  })

  it('shows the tag as it was written, not as its slug', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [published({ tags: ['las-x'] })],
      tagNames: { 'las-x': 'LAS X' },
    })
    renderApp({ route: '/t/las-x', server })

    expect(await screen.findByRole('heading', { name: 'LAS X' })).toBeInTheDocument()
    expect(screen.getByText('1 guide carries this tag.')).toBeInTheDocument()
  })

  it('says so when no guide a viewer can see carries the tag', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [guideFixture({ tags: ['stellaris'] })],
    })
    renderApp({ route: '/t/stellaris', server })

    expect(await screen.findByText('No published guides are tagged “stellaris”.')).toBeInTheDocument()
    expect(screen.getByText('0 guides carry this tag.')).toBeInTheDocument()
  })

  it('is where a tag on a guide leads', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [
        published({ tags: ['stellaris'] }),
        published({ id: 'g2', slug: 'sibling', title: 'Stellaris shutdown', tags: ['stellaris'] }),
      ],
    })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('link', { name: 'stellaris' }))

    expect(await screen.findByRole('link', { name: /Stellaris shutdown/ })).toBeInTheDocument()
    expect(location()).toBe('/t/stellaris')
  })
})

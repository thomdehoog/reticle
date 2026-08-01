import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { User } from '../domain/types'
import { categoryFixture, createFakeServer, guideFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { HomePage } from './HomePage'

const VIEWER: User = {
  id: 'u-anna',
  email: 'anna@zmb.uzh.ch',
  displayName: 'Anna Roth',
  role: 'viewer',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

function renderHome(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(<HomePage />, { route: '/', fetchImpl: server.fetchImpl })
}

describe('HomePage', () => {
  it('keeps holding categories out of the browse tree', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy' }),
        categoryFixture({ id: 'c-holding', slug: 'holding', name: 'Tag-only', isHidden: true }),
      ],
      guides: [],
    })
    renderHome(server)

    expect(await screen.findByRole('link', { name: /Light Microscopy/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Tag-only/ })).not.toBeInTheDocument()
  })

  it('counts published guides, including those in a hidden child', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy' }),
        categoryFixture({
          id: 'c-holding',
          slug: 'holding',
          name: 'Tag-only',
          parentId: 'c-light',
          isHidden: true,
        }),
      ],
      guides: [
        guideFixture({ id: 'g1', categoryId: 'c-light', status: 'published' }),
        guideFixture({ id: 'g2', slug: 'g2', categoryId: 'c-holding', status: 'published' }),
        guideFixture({ id: 'g3', slug: 'g3', categoryId: 'c-light', status: 'draft' }),
      ],
    })
    renderHome(server)

    /* The draft is not counted — the card promises guides people can read. */
    expect(await screen.findByText('2 guides')).toBeInTheDocument()
  })

  /**
   * A viewer used to download every draft in the institute so the front page
   * could put a number on eight cards. Now the only listing they ask for is the
   * published one.
   */
  it('does not pull the editorial pipeline down to a reader', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [] })
    renderHome(server)

    await screen.findByRole('heading', { name: 'Guides' })

    const listings = server.requests.filter((request) => request.path.startsWith('/guides'))
    expect(listings).toHaveLength(1)
    expect(listings[0].path).toBe('/guides?status=published')
  })

  it('shows an author their own unfinished work, and nobody else’s', async () => {
    const author: User = { ...VIEWER, role: 'author' }
    const server = createFakeServer({
      user: author,
      guides: [
        guideFixture({
          id: 'g-mine',
          title: 'Half-written STED guide',
          status: 'draft',
          author: { id: author.id, displayName: author.displayName },
        }),
        guideFixture({ id: 'g-theirs', slug: 'theirs', title: 'Somebody else’s draft', status: 'draft' }),
      ],
    })
    renderHome(server)

    expect(await screen.findByRole('link', { name: /Half-written STED guide/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Somebody else’s draft/ })).not.toBeInTheDocument()
    expect(
      server.requests.some((request) => request.path === `/guides?authorId=${author.id}`),
    ).toBe(true)
  })
})

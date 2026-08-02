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
  /* Both hold a published guide, so the only thing keeping the holding
     category off the front page is that it is a holding category. */
  it('keeps holding categories out of the browse tree', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy' }),
        categoryFixture({ id: 'c-holding', slug: 'holding', name: 'Tag-only', isHidden: true }),
      ],
      guides: [
        guideFixture({ id: 'g1', categoryId: 'c-light', status: 'published' }),
        guideFixture({ id: 'g2', slug: 'las-x', categoryId: 'c-holding', status: 'published' }),
      ],
    })
    renderHome(server)

    expect(await screen.findByRole('link', { name: /Light Microscopy/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Tag-only/ })).not.toBeInTheDocument()
  })

  /* The tile is a picture and a name. A count never decided which section
     somebody opened, and "0 guides" over a section being filled in read as a
     broken section rather than as a new one. */
  it('names a section and says nothing else about it', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ id: 'c-light', name: 'Light Microscopy' })],
      guides: [guideFixture({ id: 'g1', categoryId: 'c-light', status: 'published' })],
    })
    renderHome(server)

    const tile = await screen.findByRole('link', { name: /Light Microscopy/ })
    expect(tile).toHaveTextContent('Light Microscopy')
    expect(screen.queryByText(/guides?$/)).toBeNull()
  })

  /**
   * A viewer used to download every draft in the institute so the front page
   * could put a number on eight cards. What it asks for now is the published
   * guides — which is what decides whether a tile leads anywhere — and the
   * quick links. Neither can contain somebody's half-written work.
   */
  it('does not pull the editorial pipeline down to a reader', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [] })
    renderHome(server)

    await screen.findByRole('heading', { name: 'Guides' })

    const listings = server.requests
      .filter((request) => request.path.startsWith('/guides') || request.path.startsWith('/pages'))
      .map((request) => request.path)
      .sort()
    expect(listings).toEqual([
      '/guides?quickLink=true',
      '/guides?status=published',
      '/pages?status=published',
    ])
  })

  /* The procedures people arrive asking for, which no category name would have
     led them to. */
  it('offers the quick links, and only the guides marked as one', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          id: 'g-book',
          slug: 'book-an-instrument',
          title: 'Book an instrument',
          summary: 'PPMS in three steps',
          status: 'published',
          isQuickLink: true,
        }),
        guideFixture({
          id: 'g-other',
          slug: 'other',
          title: 'Aligning the laser',
          status: 'published',
        }),
      ],
    })
    renderHome(server)

    const link = await screen.findByRole('link', { name: /Book an instrument/ })
    expect(link).toHaveAttribute('href', '/g/book-an-instrument')
    expect(link).toHaveTextContent('PPMS in three steps')
    expect(screen.queryByRole('link', { name: /Aligning the laser/ })).not.toBeInTheDocument()
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

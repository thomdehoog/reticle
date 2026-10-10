import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Guide, Page } from '../domain/types'
import {
  createFakeServer,
  guideFixture,
  pageFixture,
  userFixture,
  type FakeRevision,
} from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })
const ANNA = { id: 'u-anna', displayName: 'Anna Author' }

const CURRENT = guideFixture({
  status: 'published',
  version: 2,
  publishedAt: '2026-03-03T10:00:00Z',
  steps: [
    {
      id: 's1',
      orderIndex: 0,
      title: 'Switch on the lasers',
      bullets: [{ id: 'b1', text: 'Turn the key to position II.', color: 'black', icon: null, level: 0 }],
      media: [],
    },
  ],
})

const FIRST: Guide = {
  ...CURRENT,
  title: 'Confocal startup (old)',
  version: 1,
  publishedAt: '2026-01-15T10:00:00Z',
  steps: [
    {
      id: 's1',
      orderIndex: 0,
      title: 'Switch on the lasers',
      bullets: [{ id: 'b1', text: 'Turn the key to position I.', color: 'red', icon: 'caution', level: 0 }],
      media: [
        {
          id: 'm1',
          kind: 'image',
          url: '/api/media/m1',
          alt: 'The key switch',
          width: 800,
          height: 600,
          annotations: [],
        },
      ],
    },
  ],
}

const GUIDE_HISTORY: FakeRevision<Guide>[] = [
  { version: 1, publishedAt: '2026-01-15T10:00:00Z', publishedBy: ANNA, snapshot: FIRST },
  { version: 2, publishedAt: '2026-03-03T10:00:00Z', publishedBy: ANNA, snapshot: CURRENT },
]

function guideServer(user = AUTHOR) {
  return createFakeServer({
    user,
    guides: [CURRENT],
    revisions: { [CURRENT.id]: GUIDE_HISTORY },
  })
}

describe('guide history', () => {
  it('lists published versions newest first, with when and by whom', async () => {
    renderApp({ route: '/g/confocal-startup/history', server: guideServer() })

    await screen.findByRole('heading', { name: 'History' })
    const rows = within(screen.getByRole('list')).getAllByRole('link')
    expect(rows.map((row) => row.getAttribute('href'))).toEqual([
      '/g/confocal-startup/v/2',
      '/g/confocal-startup/v/1',
    ])
    expect(rows[0]).toHaveTextContent('Version 2')
    expect(rows[0]).toHaveTextContent('Latest')
    expect(rows[0]).toHaveTextContent('by Anna Author')
    expect(rows[0]).toHaveTextContent('2026')
    expect(rows[1]).not.toHaveTextContent('Latest')
  })

  it('opens a past version read-only, drawn like the guide and bannered as old', async () => {
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/confocal-startup/history', server: guideServer() })

    await user.click(await screen.findByRole('link', { name: /Version 1/ }))

    expect(await screen.findByRole('heading', { name: 'Confocal startup (old)' })).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup/v/1')

    const banner = screen.getByRole('note')
    expect(banner).toHaveTextContent(/Version 1, published .*2026/)
    expect(banner).toHaveTextContent('not the current version')

    /* The snapshot's own content, through the reader's own components. */
    expect(screen.getByText('Turn the key to position I.')).toBeInTheDocument()
    expect(screen.getByText('Caution')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'The key switch' })).toBeInTheDocument()
    expect(screen.queryByText('Turn the key to position II.')).not.toBeInTheDocument()

    /* Read-only: nothing here edits, prints or downloads the old version. */
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'PDF' })).not.toBeInTheDocument()
  })

  it('does not call the newest snapshot out of date', async () => {
    renderApp({ route: '/g/confocal-startup/v/2', server: guideServer() })

    const banner = await screen.findByRole('note')
    expect(banner).toHaveTextContent('the most recent published version')
    expect(banner).not.toHaveTextContent('not the current version')
  })

  it('leads from a past version back to the list and to the live guide', async () => {
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/confocal-startup/v/1', server: guideServer() })

    await user.click(await screen.findByRole('link', { name: 'All versions' }))
    await screen.findByRole('heading', { name: 'History' })
    expect(location()).toBe('/g/confocal-startup/history')

    await user.click(screen.getByRole('link', { name: 'Back to the guide' }))
    expect(await screen.findByText('Turn the key to position II.')).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
  })

  it('does not count reading an old version as a read of the guide', async () => {
    const server = guideServer()
    renderApp({ route: '/g/confocal-startup/v/1', server })

    await screen.findByRole('note')
    expect(server.count('POST', '/guides/g-confocal/view')).toBe(0)
  })

  it('says so when a guide has never been published', async () => {
    const server = createFakeServer({ user: AUTHOR })
    renderApp({ route: '/g/confocal-startup/history', server })

    expect(await screen.findByText(/has not been published yet, so it has no history/)).toBeInTheDocument()
  })

  it.each(['/g/confocal-startup/v/9', '/g/confocal-startup/v/abc', '/g/confocal-startup/v/0'])(
    'answers a version that does not exist with the not-found screen (%s)',
    async (route) => {
      renderApp({ route, server: guideServer() })
      expect(await screen.findByText(/There is nothing here/)).toBeInTheDocument()
    },
  )

  it('is offered to authors from the reader, and kept from viewers altogether', async () => {
    const { unmount } = renderApp({ route: '/g/confocal-startup', server: guideServer() })
    expect(await screen.findByRole('link', { name: 'History' })).toHaveAttribute(
      'href',
      '/g/confocal-startup/history',
    )
    unmount()

    const asViewer = guideServer(VIEWER)
    const { location } = renderApp({ route: '/g/confocal-startup/history', server: asViewer })
    /* Sent home before anything is asked of the server on a viewer's behalf. */
    expect(await screen.findByRole('heading', { name: 'Guides' })).toBeInTheDocument()
    expect(location()).toBe('/')
    expect(asViewer.requests.some((request) => request.path.includes('/revisions'))).toBe(false)
  })

  it('records a new version in the list when the guide is published again', async () => {
    const server = guideServer()
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup/history', server })

    await screen.findByRole('link', { name: /Version 2/ })
    await user.click(screen.getByRole('link', { name: 'Back to the guide' }))
    await user.click(await screen.findByRole('link', { name: 'Edit' }))
    await user.click(await screen.findByRole('button', { name: 'Publish update' }))
    await user.click(await screen.findByRole('link', { name: 'History' }))

    expect(await screen.findByRole('link', { name: /Version 3/ })).toHaveTextContent('Latest')
  })
})

const PAGE_NOW = pageFixture({ body: 'Use **oil** for the 63x.', version: 2 })
const PAGE_THEN: Page = { ...PAGE_NOW, body: 'Use water for everything.', version: 1 }
const PAGE_HISTORY: FakeRevision<Page>[] = [
  { version: 1, publishedAt: '2026-01-15T10:00:00Z', publishedBy: ANNA, snapshot: PAGE_THEN },
  { version: 2, publishedAt: '2026-03-03T10:00:00Z', publishedBy: ANNA, snapshot: PAGE_NOW },
]

function pageServer(user = AUTHOR) {
  return createFakeServer({
    user,
    pages: [PAGE_NOW],
    revisions: { [PAGE_NOW.id]: PAGE_HISTORY },
  })
}

describe('wiki page history', () => {
  it('lists versions and opens one as it was, rendered as Markdown', async () => {
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/w/choosing-an-objective/history', server: pageServer() })

    await user.click(await screen.findByRole('link', { name: /Version 1/ }))

    expect(await screen.findByText('Use water for everything.')).toBeInTheDocument()
    expect(location()).toBe('/w/choosing-an-objective/v/1')
    expect(screen.getByRole('note')).toHaveTextContent('not the current version')
    expect(screen.queryByText(/for the 63x/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })

  it('is offered from the page reader to authors only', async () => {
    const { unmount } = renderApp({ route: '/w/choosing-an-objective', server: pageServer() })
    expect(await screen.findByRole('link', { name: 'History' })).toHaveAttribute(
      'href',
      '/w/choosing-an-objective/history',
    )
    unmount()

    renderApp({ route: '/w/choosing-an-objective', server: pageServer(VIEWER) })
    await screen.findByRole('article')
    expect(screen.queryByRole('link', { name: 'History' })).not.toBeInTheDocument()
  })

  it('is offered from the page editor', async () => {
    renderApp({ route: '/w/p-objectives/edit', server: pageServer() })

    expect(await screen.findByRole('link', { name: 'History' })).toHaveAttribute(
      'href',
      '/w/choosing-an-objective/history',
    )
  })
})

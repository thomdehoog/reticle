import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { createFakeServer, guideFixture, pageFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })

const published = (overrides: Parameters<typeof guideFixture>[0] = {}) =>
  guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1, ...overrides })

function section(name: RegExp): HTMLElement {
  return screen.getByRole('heading', { name }).parentElement as HTMLElement
}

describe('SearchPage', () => {
  it('shows guides and wiki pages as separate groups, each with a count', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [published(), published({ id: 'g2', slug: 'sted', title: 'STED alignment' })],
      pages: [pageFixture({ title: 'Confocal theory', slug: 'confocal-theory' })],
    })
    renderApp({ route: '/search?q=confocal', server })

    expect(await screen.findByText('Results for “confocal”')).toBeInTheDocument()

    const guides = section(/^Guides/)
    expect(within(guides).getByText('1')).toBeInTheDocument()
    expect(within(guides).getByRole('link', { name: /Confocal startup/ })).toHaveAttribute(
      'href',
      '/g/confocal-startup',
    )

    const pages = section(/^Wiki pages/)
    expect(within(pages).getByRole('link', { name: /Confocal theory/ })).toHaveAttribute(
      'href',
      '/w/confocal-theory',
    )
    expect(screen.queryByText('STED alignment')).not.toBeInTheDocument()
  })

  it('says so when nothing matches', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route: '/search?q=cryostat', server })

    expect(await screen.findByText(/Nothing matches “cryostat”/)).toBeInTheDocument()
  })

  it('asks the server nothing when there is no term', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route: '/search', server })

    expect(await screen.findByText('Type a search term above.')).toBeInTheDocument()
    expect(server.count('GET', '/search')).toBe(0)
  })

  it.each([
    ['/search?q=488', '488'],
    ['/search?q=true', 'true'],
    ['/search?q=%22quoted%22', '"quoted"'],
    ['/search?q=live+cell', 'live cell'],
  ])('reads %s as the text %s', async (route, term) => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route, server })

    await screen.findByText(`Results for “${term}”`)
    expect(server.requests.find((request) => request.path === '/search')?.query.get('q')).toBe(term)
  })

  it('treats a malformed parameter as no search at all', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route: '/search?other=1&q=', server })

    expect(await screen.findByText('Type a search term above.')).toBeInTheDocument()
  })

  it('shows the current term in the header box, and follows a new one', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [published(), published({ id: 'g2', slug: 'sted', title: 'STED alignment' })],
    })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/search?q=confocal', server })

    const box = await screen.findByLabelText('Search guides')
    expect(box).toHaveValue('confocal')

    await user.clear(box)
    await user.type(box, 'sted{Enter}')

    expect(await screen.findByRole('link', { name: /STED alignment/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Confocal startup/ })).not.toBeInTheDocument()
    expect(location()).toBe('/search?q=sted')
  })

  it('does not find a draft for a viewer', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [guideFixture()] })
    renderApp({ route: '/search?q=confocal', server })

    expect(await screen.findByText(/Nothing matches/)).toBeInTheDocument()
  })
})

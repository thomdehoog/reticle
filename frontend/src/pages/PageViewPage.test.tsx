import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { createFakeServer, guideFixture, pageFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const published = (overrides: Parameters<typeof guideFixture>[0] = {}) =>
  guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1, ...overrides })

const ARTICLE = pageFixture({
  summary: 'Numerical aperture, immersion and working distance.',
  categoryId: 'c-light',
  body: [
    '## Immersion',
    '',
    'Match the **immersion medium** to the objective.',
    '',
    'See [the startup guide](/g/confocal-startup) or [ZMB](https://www.zmb.uzh.ch/).',
    '',
    '```guidelist',
    'tags: objectives',
    'heading: Related guides',
    '```',
  ].join('\n'),
})

describe('PageViewPage', () => {
  it('renders the page: title, summary, formatted body and its category', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE] })
    renderApp({ route: '/w/choosing-an-objective', server })

    const article = await screen.findByRole('article')
    expect(within(article).getByRole('heading', { level: 1, name: 'Choosing an objective' }))
      .toBeInTheDocument()
    expect(within(article).getByText('Numerical aperture, immersion and working distance.'))
      .toBeInTheDocument()
    expect(within(article).getByRole('heading', { level: 2, name: 'Immersion' })).toBeInTheDocument()
    expect(within(article).getByText('immersion medium').tagName).toBe('STRONG')
    expect(within(article).getByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
  })

  it('embeds the guides a guide-list block asks for', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [ARTICLE],
      guides: [
        published({ id: 'g1', slug: 'cleaning', title: 'Cleaning an objective', tags: ['objectives'] }),
        published({ id: 'g2', slug: 'other', title: 'Unrelated guide', tags: ['zen'] }),
        guideFixture({ id: 'g3', slug: 'draft', title: 'Draft about objectives', tags: ['objectives'] }),
      ],
    })
    renderApp({ route: '/w/choosing-an-objective', server })

    expect(await screen.findByRole('heading', { name: 'Related guides' })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /Cleaning an objective/ })).toHaveAttribute(
      'href',
      '/g/cleaning',
    )
    expect(screen.queryByText('Unrelated guide')).not.toBeInTheDocument()
    expect(screen.queryByText('Draft about objectives')).not.toBeInTheDocument()
  })

  it('follows an in-app link in the body without leaving the app', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE], guides: [published()] })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/w/choosing-an-objective', server })

    await user.click(await screen.findByRole('link', { name: 'the startup guide' }))

    expect(await screen.findByRole('heading', { name: /Step 1: Switch on the lasers/ }))
      .toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
    /* One session check for the whole visit: the app was never reloaded. */
    expect(server.count('GET', '/auth/me')).toBe(1)
  })

  it('sends an in-app link to nowhere back home rather than breaking', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [pageFixture({ body: 'A [stale link](/old/section/that/moved).' })],
    })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/w/choosing-an-objective', server })

    await user.click(await screen.findByRole('link', { name: 'stale link' }))

    expect(await screen.findByRole('heading', { name: 'Guides' })).toBeInTheDocument()
    expect(location()).toBe('/')
  })

  it('opens an external link in a new tab', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE] })
    renderApp({ route: '/w/choosing-an-objective', server })

    const link = await screen.findByRole('link', { name: 'ZMB' })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('records one read per visit', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE] })
    renderApp({ route: '/w/choosing-an-objective', server })

    await screen.findByRole('article')
    await waitFor(() => expect(server.count('POST', '/pages/p-objectives/view')).toBe(1))
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(server.count('POST', '/pages/p-objectives/view')).toBe(1)
  })

  it('shows the hero image when the page has one', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [pageFixture({ heroMediaId: 'm-hero' })],
    })
    renderApp({ route: '/w/choosing-an-objective', server })

    const article = await screen.findByRole('article')
    expect(article.querySelector('img')).toHaveAttribute('src', '/api/media/m-hero')
  })

  it('offers Edit to an author and marks a draft as one', async () => {
    const server = createFakeServer({ user: AUTHOR, pages: [pageFixture({ status: 'draft' })] })
    renderApp({ route: '/w/choosing-an-objective', server })

    expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/w/p-objectives/edit',
    )
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('offers a viewer no Edit, and no draft at all', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [ARTICLE, pageFixture({ id: 'p-draft', slug: 'unfinished', status: 'draft' })],
    })
    const { unmount } = renderApp({ route: '/w/choosing-an-objective', server })

    await screen.findByRole('article')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    unmount()

    renderApp({ route: '/w/unfinished', server })
    expect(await screen.findByText(/There is nothing here/)).toBeInTheDocument()
  })
})

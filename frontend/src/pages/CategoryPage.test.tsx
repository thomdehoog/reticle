import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  pageFixture,
  userFixture,
} from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const published = (overrides: Parameters<typeof guideFixture>[0] = {}) =>
  guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1, ...overrides })

const LIGHT = categoryFixture()
const CONFOCAL = categoryFixture({
  id: 'c-confocal',
  slug: 'confocal',
  name: 'Confocal',
  description: 'Point-scanning systems',
  parentId: 'c-light',
})
const HOLDING = categoryFixture({
  id: 'c-hold',
  slug: 'confocal-hidden-guides',
  name: 'Confocal - hidden guides',
  parentId: 'c-light',
  isHidden: true,
})

const LANDING = pageFixture({
  id: 'p-landing',
  slug: 'light-microscopy-landing',
  title: 'Light microscopy',
  categoryId: 'c-light',
  isLanding: true,
  body: 'Start here if you are new to the facility.\n\n```guidelist\ntags: stellaris\nheading: Stellaris 5\n```',
})

afterEach(() => vi.restoreAllMocks())

describe('CategoryPage', () => {
  it('lists the guides filed in the category, and only those', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [LIGHT, CONFOCAL],
      guides: [
        published({ id: 'g1', slug: 'one', title: 'Widefield startup' }),
        published({ id: 'g2', slug: 'two', title: 'Stellaris startup', categoryId: 'c-confocal' }),
      ],
    })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByRole('heading', { name: 'Light Microscopy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Widefield startup/ })).toHaveAttribute('href', '/g/one')
    expect(screen.queryByText('Stellaris startup')).not.toBeInTheDocument()
    expect(server.requests.some((r) => r.path === '/guides' && r.query.get('categoryId') === 'c-light'))
      .toBe(true)
  })

  it('shows sub-categories and a breadcrumb back to the parent', async () => {
    const server = createFakeServer({ user: VIEWER, categories: [LIGHT, CONFOCAL, HOLDING] })
    renderApp({ route: '/c/light-microscopy', server })

    const child = await screen.findByRole('link', { name: /Confocal/ })
    expect(child).toHaveAttribute('href', '/c/confocal')
    expect(within(child).getByText('Point-scanning systems')).toBeInTheDocument()
    /* A hidden sub-category is not offered for browsing either. */
    expect(screen.queryByText('Confocal - hidden guides')).not.toBeInTheDocument()
  })

  it('links a sub-category back to its parent', async () => {
    const server = createFakeServer({ user: VIEWER, categories: [LIGHT, CONFOCAL] })
    renderApp({ route: '/c/confocal', server })

    await screen.findByRole('heading', { name: 'Confocal' })
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
  })

  it('still resolves a hidden category by its URL', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [LIGHT, HOLDING],
      guides: [published({ title: 'LAS X navigator', categoryId: 'c-hold' })],
    })
    renderApp({ route: '/c/confocal-hidden-guides', server })

    expect(await screen.findByRole('heading', { name: 'Confocal - hidden guides' })).toBeInTheDocument()
    expect(screen.getByText('LAS X navigator')).toBeInTheDocument()
  })

  it('renders the landing page, with the guide lists it embeds', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [LANDING],
      guides: [
        published({
          id: 'g-held',
          slug: 'stellaris-startup',
          title: 'Stellaris startup',
          categoryId: 'c-elsewhere',
          tags: ['stellaris'],
        }),
      ],
    })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByText('Start here if you are new to the facility.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Stellaris 5' })).toBeInTheDocument()
    /* The guide lives in another category and arrives here through its tag. */
    expect(await screen.findByRole('link', { name: /Stellaris startup/ })).toHaveAttribute(
      'href',
      '/g/stellaris-startup',
    )
    expect(screen.queryByText('Nothing in this category yet.')).not.toBeInTheDocument()
  })

  it('counts reading a landing page as one read of that page', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [LANDING] })
    renderApp({ route: '/c/light-microscopy', server })

    await screen.findByText('Start here if you are new to the facility.')
    await waitFor(() => expect(server.count('POST', '/pages/p-landing/view')).toBe(1))
  })

  it('does not show a viewer a landing page that is still a draft', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [{ ...LANDING, status: 'draft' }],
      guides: [],
    })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByText('Nothing in this category yet.')).toBeInTheDocument()
    expect(screen.queryByText('Start here if you are new to the facility.')).not.toBeInTheDocument()
  })

  it('lets an author open the landing page in the editor', async () => {
    const server = createFakeServer({ user: AUTHOR, pages: [LANDING] })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByRole('link', { name: 'Edit landing page' })).toHaveAttribute(
      'href',
      '/w/p-landing/edit',
    )
  })

  it('lets an author start a landing page where there is none', async () => {
    const server = createFakeServer({ user: AUTHOR })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/c/light-microscopy', server })

    await user.click(await screen.findByRole('button', { name: 'Write this page' }))
    expect(screen.getByLabelText('Title')).toHaveValue('Light Microscopy')
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    await screen.findByLabelText('Page content (Markdown)')
    expect(location()).toBe('/w/p-new-1/edit')
    expect(server.state.pages[0]).toMatchObject({ categoryId: 'c-light', isLanding: true })
    expect(screen.getByLabelText(/Use as this category/)).toBeChecked()
  })

  it('says so when the category does not exist', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ route: '/c/never-created', server })

    expect(await screen.findByText(/There is nothing here/)).toBeInTheDocument()
  })

  it('lets an admin hide a category, which takes it off the home page', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderApp({ route: '/c/light-microscopy', server })

    await user.click(await screen.findByRole('button', { name: 'Edit category' }))
    await user.click(screen.getByLabelText('Hide from browsing'))
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(server.state.categories[0].isHidden).toBe(true))
    expect(server.requests.find((request) => request.method === 'PATCH')?.body).toMatchObject({
      isHidden: true,
    })

    await user.click(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByRole('link', { name: 'Guides' }))
    await screen.findByRole('heading', { name: 'Hidden categories' })
    expect(screen.queryByText('Light Microscopy', { selector: '.category-card__name' })).toBeNull()
  })

  it('follows a renamed category to its new address', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/c/light-microscopy', server })

    await user.click(await screen.findByRole('button', { name: 'Edit category' }))
    await user.clear(screen.getByLabelText('Name'))
    await user.type(screen.getByLabelText('Name'), 'Optical Microscopy')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('heading', { name: 'Optical Microscopy' })).toBeInTheDocument()
    expect(location()).toBe('/c/optical-microscopy')
  })

  it('reports why a category that still holds guides cannot be deleted', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const server = createFakeServer()
    const user = userEvent.setup()
    renderApp({ route: '/c/light-microscopy', server })

    await user.click(await screen.findByRole('button', { name: 'Edit category' }))
    await user.click(screen.getByRole('button', { name: 'Delete' }))

    expect(await screen.findByText(/still holds guides/)).toBeInTheDocument()
    expect(server.state.categories).toHaveLength(1)
  })
})

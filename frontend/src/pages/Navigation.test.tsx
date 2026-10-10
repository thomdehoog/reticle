/**
 * Getting around: the header, breadcrumbs, tag chips on listings, and what a
 * category shows when it has no landing page.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

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
  parentId: 'c-light',
})
const STELLARIS = categoryFixture({
  id: 'c-stellaris',
  slug: 'stellaris',
  name: 'Stellaris 5',
  parentId: 'c-confocal',
})

function crumbs(): string[] {
  const trail = screen.getByRole('navigation', { name: 'Breadcrumb' })
  return Array.from(trail.querySelectorAll('a, span:not(.breadcrumb__sep)')).map(
    (node) => node.textContent ?? '',
  )
}

describe('the header', () => {
  it('offers the three ways in to everyone, and People to an admin only', async () => {
    const { unmount } = renderApp({ server: createFakeServer({ user: VIEWER }) })

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(nav).getAllByRole('link').map((link) => link.textContent)).toEqual([
      'Guides',
      'Wiki',
      'Tags',
    ])
    expect(within(nav).getByRole('link', { name: 'Guides' })).toHaveAttribute('aria-current', 'page')
    unmount()

    renderApp({ server: createFakeServer() })
    const adminNav = await screen.findByRole('navigation', { name: 'Main' })
    expect(within(adminNav).getByRole('link', { name: 'People' })).toHaveAttribute('href', '/users')
  })

  it('says that the search covers pages as well as guides', async () => {
    renderApp({ server: createFakeServer({ user: VIEWER }) })

    expect(await screen.findByPlaceholderText('Search guides and pages…')).toHaveAccessibleName(
      'Search guides and wiki pages',
    )
  })

  it('keeps Sign out a named button whatever it looks like', async () => {
    renderApp({ server: createFakeServer({ user: VIEWER }) })

    expect(await screen.findByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })
})

describe('breadcrumbs', () => {
  it('trace a guide through every level of its category', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [LIGHT, CONFOCAL, STELLARIS],
      guides: [published({ categoryId: 'c-stellaris' })],
    })
    renderApp({ route: '/g/confocal-startup', server })

    await screen.findByRole('article')
    expect(crumbs()).toEqual(['Guides', 'Light Microscopy', 'Confocal', 'Stellaris 5'])
  })

  it('show the category in the guide editor, which used to stop at "Editing"', async () => {
    const server = createFakeServer({ categories: [LIGHT, CONFOCAL], guides: [guideFixture({ categoryId: 'c-confocal' })] })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/g-confocal/edit', server })

    await screen.findByDisplayValue('Switch on the lasers')
    expect(crumbs()).toEqual(['Guides', 'Light Microscopy', 'Confocal', 'Editing'])

    await user.click(
      within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByRole('link', {
        name: 'Confocal',
      }),
    )
    await screen.findByRole('heading', { name: 'Confocal' })
    expect(location()).toBe('/c/confocal')
  })

  it('follow the guide when the author files it somewhere else', async () => {
    const server = createFakeServer({ categories: [LIGHT, CONFOCAL] })
    const user = userEvent.setup()
    renderApp({ route: '/g/g-confocal/edit', server })

    await screen.findByDisplayValue('Switch on the lasers')
    expect(crumbs()).toEqual(['Guides', 'Light Microscopy', 'Editing'])

    await user.selectOptions(screen.getByLabelText('Category'), 'Confocal')

    expect(crumbs()).toEqual(['Guides', 'Light Microscopy', 'Confocal', 'Editing'])
  })

  it('show a nested category\'s ancestors, linked, and the category itself as text', async () => {
    const server = createFakeServer({ user: VIEWER, categories: [LIGHT, CONFOCAL, STELLARIS] })
    renderApp({ route: '/c/stellaris', server })

    await screen.findByRole('heading', { name: 'Stellaris 5' })
    expect(crumbs()).toEqual(['Guides', 'Light Microscopy', 'Confocal', 'Stellaris 5'])
    const trail = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(trail).queryByRole('link', { name: 'Stellaris 5' })).not.toBeInTheDocument()
  })
})

describe('tag chips on listings', () => {
  it('lead from a guide row to the tag, while the row itself leads to the guide', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [published({ tags: ['las-x', 'confocal'] })],
      tagNames: { 'las-x': 'LAS X' },
    })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/c/light-microscopy', server })

    const title = await screen.findByRole('link', { name: 'Confocal startup' })
    expect(title).toHaveAttribute('href', '/g/confocal-startup')
    const row = title.closest('.guide-row') as HTMLElement
    /* Two separate links side by side — never one inside the other. */
    expect(title.querySelector('a')).toBeNull()

    await user.click(await within(row).findByRole('link', { name: 'LAS X' }))

    expect(await screen.findByRole('heading', { name: 'LAS X' })).toBeInTheDocument()
    expect(location()).toBe('/t/las-x')
  })

  it('show the first few tags of a heavily tagged guide and count the rest', async () => {
    const tags = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
    const server = createFakeServer({ user: VIEWER, guides: [published({ tags })] })
    renderApp({ route: '/c/light-microscopy', server })

    const row = (await screen.findByRole('link', { name: 'Confocal startup' })).closest(
      '.guide-row',
    ) as HTMLElement
    expect(within(row).getAllByRole('link')).toHaveLength(1 + 4)
    expect(within(row).getByText('+3 more')).toBeInTheDocument()
  })

  it('appear in search results too', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [published({ tags: ['stellaris'] })],
    })
    renderApp({ route: '/search?q=confocal', server })

    expect(await screen.findByRole('link', { name: 'stellaris' })).toHaveAttribute(
      'href',
      '/t/stellaris',
    )
  })
})

describe('a category without a landing page', () => {
  it('tells an author so, with the way to write one', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [published()] })
    const user = userEvent.setup()
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByText('This category has no landing page yet.')).toBeInTheDocument()
    /* Its guides are still listed underneath. */
    expect(screen.getByRole('link', { name: 'Confocal startup' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Write this page' }))
    expect(screen.getByRole('dialog', { name: 'New landing page' })).toBeInTheDocument()
  })

  it('shows a viewer the guides and nothing about what is missing', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [published()] })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByRole('link', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(screen.queryByText(/no landing page/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Write this page' })).not.toBeInTheDocument()
  })

  it('stops offering to write one once it exists, and marks a draft landing as a draft', async () => {
    const server = createFakeServer({
      user: AUTHOR,
      pages: [
        pageFixture({
          id: 'p-landing',
          slug: 'light',
          categoryId: 'c-light',
          isLanding: true,
          status: 'draft',
          body: 'Start here.',
        }),
      ],
    })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByText('Start here.')).toBeInTheDocument()
    expect(screen.getByText('The landing page below is a draft.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Write this page' })).not.toBeInTheDocument()
  })

  it('shows landing content, sub-categories, wiki pages and guides together', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [LIGHT, CONFOCAL],
      guides: [published()],
      pages: [
        pageFixture({ id: 'p-l', slug: 'light', categoryId: 'c-light', isLanding: true, body: 'Start here.' }),
        pageFixture({ id: 'p-a', slug: 'oil', title: 'Immersion oil', categoryId: 'c-light' }),
      ],
    })
    renderApp({ route: '/c/light-microscopy', server })

    expect(await screen.findByText('Start here.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'In this category' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Confocal$/ })).toHaveAttribute('href', '/c/confocal')
    expect(screen.getByRole('heading', { name: 'Wiki pages' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Immersion oil' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Guides in this category' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Confocal startup' })).toBeInTheDocument()
  })
})

describe('the wiki page reader', () => {
  it('says who wrote a page, who else worked on it, and when it last changed', async () => {
    const anna = { id: 'u-anna', displayName: 'Anna Author' }
    const ben = { id: 'u-ben', displayName: 'Ben Bench' }
    const server = createFakeServer({
      user: VIEWER,
      pages: [
        pageFixture({
          author: anna,
          contributors: [anna, ben],
          lastEditedBy: ben,
          updatedAt: '2026-03-03T10:00:00Z',
          publishedAt: '2026-03-03T10:00:00Z',
          version: 4,
        }),
      ],
    })
    renderApp({ route: '/w/choosing-an-objective', server })

    const footer = (await screen.findByText(/Written by Anna Author, with Ben Bench\./)).closest(
      'footer',
    ) as HTMLElement
    expect(footer).toHaveTextContent(/Last edited .*2026 by Ben Bench/)
    expect(footer).toHaveTextContent(/version 4, published .*2026/)
  })

  it('does not name the author twice when nobody else has edited it', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [pageFixture()] })
    renderApp({ route: '/w/choosing-an-objective', server })

    const footer = (await screen.findByText('Written by Thom de Hoog.')).closest('footer') as HTMLElement
    expect(footer).not.toHaveTextContent(/Last edited .* by/)
  })

  it('tells an author in words that a draft page is not what readers see', async () => {
    const server = createFakeServer({ user: AUTHOR, pages: [pageFixture({ status: 'draft' })] })
    renderApp({ route: '/w/choosing-an-objective', server })

    expect(await screen.findByText('This page is a draft.')).toBeInTheDocument()
  })
})

describe('the guide editor', () => {
  it('drops a publish problem from the list as soon as it is fixed', async () => {
    const server = createFakeServer({ guides: [guideFixture({ title: '' })] })
    const user = userEvent.setup()
    renderApp({ route: '/g/g-confocal/edit', server })

    await screen.findByDisplayValue('Switch on the lasers')
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    expect(screen.getByText('A guide needs a title before it can be published.')).toBeInTheDocument()

    await user.type(screen.getByLabelText('Title'), 'Confocal startup')

    expect(screen.queryByText(/is not ready to publish/)).not.toBeInTheDocument()
  })

  it('draws each bullet\'s marker in the colour chosen for it', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          steps: [
            {
              id: 's1',
              orderIndex: 0,
              title: 'Mount',
              bullets: [
                { id: 'b1', text: 'Green one.', color: 'green', icon: null, level: 0 },
                { id: 'b2', text: 'Careful.', color: 'black', icon: 'caution', level: 0 },
              ],
              media: [],
            },
          ],
        }),
      ],
    })
    renderApp({ route: '/g/g-confocal/edit', server })

    const green = (await screen.findByDisplayValue('Green one.')).closest('.editor-bullet')
    expect(green).toHaveClass('bullet--color-green')
    /* A flag takes the colour of its kind, as it does for the reader. */
    expect(screen.getByDisplayValue('Careful.').closest('.editor-bullet')).toHaveClass(
      'bullet--kind-caution',
    )
  })

  it('announces the save state from a live region that is there from the start', async () => {
    renderApp({ route: '/g/g-confocal/edit', server: createFakeServer() })

    const state = await screen.findByText('All changes saved')
    expect(state).toHaveAttribute('role', 'status')
    expect(state).toHaveAttribute('aria-live', 'polite')
  })

  it('sends a new tag in the author\'s spelling, so the server can name it properly', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderApp({ route: '/g/g-confocal/edit', server })

    await screen.findByDisplayValue('Switch on the lasers')
    await user.type(screen.getByLabelText('Add a tag'), 'LAS X{Enter}')

    await waitFor(
      () => {
        const save = server.requests.find((request) => request.method === 'PUT')
        expect((save?.body as { tags: string[] }).tags).toEqual(['LAS X'])
      },
      { timeout: 4000 },
    )
  })
})

import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { categoryFixture, createFakeServer, pageFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const ARTICLE = pageFixture()
const FILED = pageFixture({
  id: 'p-oil',
  slug: 'immersion-oil',
  title: 'Immersion oil',
  categoryId: 'c-light',
})
const LANDING = pageFixture({
  id: 'p-landing',
  slug: 'light-microscopy',
  title: 'Light microscopy at ZMB',
  categoryId: 'c-light',
  isLanding: true,
})
const DRAFT = pageFixture({
  id: 'p-draft',
  slug: 'unfinished',
  title: 'Unfinished thoughts',
  status: 'draft',
  publishedAt: null,
  version: 0,
})

function section(name: string): HTMLElement {
  return screen.getByRole('heading', { name }).closest('section') as HTMLElement
}

describe('WikiIndexPage', () => {
  it('lists standalone articles, which have no category to be found through', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE, FILED, LANDING] })
    renderApp({ route: '/wiki', server })

    await screen.findByRole('heading', { name: 'Wiki' })
    const articles = within(section('Articles'))
    expect(articles.getByRole('link', { name: 'Choosing an objective' })).toHaveAttribute(
      'href',
      '/w/choosing-an-objective',
    )
    /* A page filed in a category is an article too, and says where it lives. */
    expect(articles.getByRole('link', { name: 'Immersion oil' })).toBeInTheDocument()
    expect(articles.getByText('In Light Microscopy')).toBeInTheDocument()
  })

  it('lists category landing pages apart from the articles', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE, LANDING] })
    renderApp({ route: '/wiki', server })

    await screen.findByRole('heading', { name: 'Wiki' })
    const landings = within(section('Category pages'))
    expect(landings.getByRole('link', { name: 'Light microscopy at ZMB' })).toBeInTheDocument()
    expect(landings.queryByRole('link', { name: 'Choosing an objective' })).not.toBeInTheDocument()
  })

  it('shows an author their drafts, marked, and hides them from a viewer', async () => {
    const asAuthor = createFakeServer({ user: AUTHOR, pages: [ARTICLE, DRAFT] })
    const { unmount } = renderApp({ route: '/wiki', server: asAuthor })

    const row = (await screen.findByRole('link', { name: 'Unfinished thoughts' })).closest(
      '.guide-row',
    ) as HTMLElement
    expect(within(row).getByText('Draft')).toBeInTheDocument()
    unmount()

    const asViewer = createFakeServer({ user: VIEWER, pages: [ARTICLE, DRAFT] })
    renderApp({ route: '/wiki', server: asViewer })
    await screen.findByRole('link', { name: 'Choosing an objective' })
    expect(screen.queryByRole('link', { name: 'Unfinished thoughts' })).not.toBeInTheDocument()
  })

  it('lets an author start a page from here, and offers a viewer nothing to press', async () => {
    const server = createFakeServer({ user: AUTHOR, pages: [] })
    const user = userEvent.setup()
    const { location, unmount } = renderApp({ route: '/wiki', server })

    expect(await screen.findByText('There are no wiki pages yet.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Write the first page' }))
    await user.type(screen.getByLabelText('Title'), 'Booking rules')
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    await screen.findByLabelText('Page content (Markdown)')
    expect(location()).toBe('/w/p-new-1/edit')
    expect(server.state.pages[0]).toMatchObject({ title: 'Booking rules', categoryId: null })
    unmount()

    renderApp({ route: '/wiki', server: createFakeServer({ user: VIEWER, pages: [] }) })
    expect(await screen.findByText('There are no wiki pages yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /wiki page|first page/i })).not.toBeInTheDocument()
  })

  it('is linked from the header and from the home page', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [categoryFixture()],
      pages: [ARTICLE],
    })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/', server })

    await user.click(await screen.findByRole('link', { name: 'All wiki pages' }))
    expect(await screen.findByRole('heading', { name: 'Wiki' })).toBeInTheDocument()
    expect(location()).toBe('/wiki')
    expect(
      within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Wiki' }),
    ).toHaveAttribute('aria-current', 'page')
  })

  it('gives a standalone article a way back to the index', async () => {
    const server = createFakeServer({ user: VIEWER, pages: [ARTICLE] })
    renderApp({ route: '/w/choosing-an-objective', server })

    await screen.findByRole('article')
    expect(
      within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByRole('link', {
        name: 'Wiki',
      }),
    ).toHaveAttribute('href', '/wiki')
  })
})

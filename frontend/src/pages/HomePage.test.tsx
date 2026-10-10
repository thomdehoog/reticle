import { screen, within } from '@testing-library/react'
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
  orderIndex: 0,
})
const HOLDING = categoryFixture({
  id: 'c-hold',
  slug: 'confocal-hidden-guides',
  name: 'Confocal - hidden guides',
  isHidden: true,
  orderIndex: 9,
})

function card(name: string): HTMLElement {
  return screen.getByText(name, { selector: '.category-card__name' }).closest('a') as HTMLElement
}

describe('HomePage', () => {
  it('counts published guides per top-level category, sub-categories included', async () => {
    const server = createFakeServer({
      categories: [LIGHT, CONFOCAL],
      guides: [
        published({ id: 'g1', slug: 'one' }),
        published({ id: 'g2', slug: 'two', categoryId: 'c-confocal' }),
        guideFixture({ id: 'g3', slug: 'three', title: 'Still a draft' }),
      ],
    })
    renderApp({ server })

    await screen.findByRole('heading', { name: 'Guides' })
    expect(within(card('Light Microscopy')).getByText('2 guides')).toBeInTheDocument()
    /* Only top-level categories get a card; the rest are one click down. */
    expect(screen.queryByText('Confocal', { selector: '.category-card__name' })).toBeNull()
  })

  it('leaves a hidden category out of the browsable tree', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [LIGHT, HOLDING],
      guides: [published({ categoryId: 'c-hold' })],
    })
    renderApp({ server })

    await screen.findByRole('heading', { name: 'Guides' })
    expect(card('Light Microscopy')).toBeInTheDocument()
    expect(screen.queryByText('Confocal - hidden guides')).not.toBeInTheDocument()
  })

  it('still gives authors a way to the hidden categories they file guides in', async () => {
    const server = createFakeServer({ user: AUTHOR, categories: [LIGHT, HOLDING] })
    renderApp({ server })

    const link = await screen.findByRole('link', { name: 'Confocal - hidden guides' })
    expect(link).toHaveAttribute('href', '/c/confocal-hidden-guides')
    expect(link).not.toHaveClass('category-card')
  })

  it('promotes a visible category whose parent is hidden rather than losing it', async () => {
    const server = createFakeServer({
      user: VIEWER,
      categories: [HOLDING, { ...CONFOCAL, parentId: 'c-hold' }],
    })
    renderApp({ server })

    await screen.findByRole('heading', { name: 'Guides' })
    expect(card('Confocal')).toBeInTheDocument()
  })

  it("lists an author's own unpublished guides, linked to the editor", async () => {
    const mine = { id: AUTHOR.id, displayName: AUTHOR.displayName }
    const server = createFakeServer({
      user: AUTHOR,
      guides: [
        guideFixture({ id: 'g-mine', slug: 'mine', title: 'My half-written guide', author: mine }),
        guideFixture({ id: 'g-theirs', slug: 'theirs', title: "A colleague's draft" }),
      ],
    })
    renderApp({ server })

    const section = (await screen.findByRole('heading', { name: 'Your unpublished guides' }))
      .parentElement as HTMLElement
    expect(within(section).getByRole('link', { name: /My half-written guide/ })).toHaveAttribute(
      'href',
      '/g/g-mine/edit',
    )
    expect(within(section).queryByText("A colleague's draft")).not.toBeInTheDocument()
  })

  it('lists wiki articles but not category landing pages', async () => {
    const server = createFakeServer({
      user: VIEWER,
      pages: [
        pageFixture(),
        pageFixture({
          id: 'p-landing',
          slug: 'light-landing',
          title: 'About light microscopy',
          categoryId: 'c-light',
          isLanding: true,
        }),
        pageFixture({ id: 'p-draft', slug: 'draft', title: 'Unfinished article', status: 'draft' }),
      ],
    })
    renderApp({ server })

    expect(await screen.findByRole('link', { name: /Choosing an objective/ })).toHaveAttribute(
      'href',
      '/w/choosing-an-objective',
    )
    expect(screen.queryByText('About light microscopy')).not.toBeInTheDocument()
    expect(screen.queryByText('Unfinished article')).not.toBeInTheDocument()
  })

  it('offers authoring controls only to the roles that can use them', async () => {
    const server = createFakeServer({ user: VIEWER })
    renderApp({ server })

    await screen.findByRole('heading', { name: 'Guides' })
    expect(screen.queryByRole('button', { name: 'New guide' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New wiki page' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'New category' })).not.toBeInTheDocument()
  })

  it('creates a wiki page and opens it in the editor', async () => {
    const server = createFakeServer({ user: AUTHOR })
    const user = userEvent.setup()
    const { location } = renderApp({ server })

    await user.click(await screen.findByRole('button', { name: 'New wiki page' }))
    await user.type(screen.getByLabelText('Title'), 'Köhler illumination')
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    expect(await screen.findByLabelText('Page content (Markdown)')).toBeInTheDocument()
    expect(location()).toBe('/w/p-new-1/edit')
    expect(server.state.pages[0]).toMatchObject({ categoryId: null, isLanding: false })
  })

  it('lets an admin add a category, and shows it without a reload', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderApp({ server })

    await user.click(await screen.findByRole('button', { name: 'New category' }))
    await user.type(screen.getByLabelText('Name'), 'Electron Microscopy')
    await user.click(screen.getByRole('button', { name: 'Create category' }))

    expect(await screen.findByText('Electron Microscopy', { selector: '.category-card__name' }))
      .toBeInTheDocument()
    expect(server.state.categories).toHaveLength(2)
  })
})

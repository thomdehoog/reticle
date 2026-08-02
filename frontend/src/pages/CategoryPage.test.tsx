import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { categoryFixture, createFakeServer, guideFixture, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { CategoryPage } from './CategoryPage'

function renderCategory(server: ReturnType<typeof createFakeServer>, slug = 'light-microscopy') {
  return renderWithApp(
    <Routes>
      <Route path="/c/:slug" element={<CategoryPage />} />
      <Route path="/w/:id/edit" element={<div>Editing the landing page</div>} />
    </Routes>,
    { route: `/c/${slug}`, fetchImpl: server.fetchImpl },
  )
}

describe('CategoryPage', () => {
  it('falls back to a plain list when nobody has written a landing page', async () => {
    const server = createFakeServer({
      guides: [guideFixture({ status: 'published', title: 'Confocal startup' })],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Confocal startup/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Write a landing page/ })).toBeInTheDocument()
  })

  /**
   * Each level of the tree shows one thing.
   *
   * A category with sub-categories shows those and stops: the guides belong to
   * the level below, and listing them here as well is the same procedures
   * twice, once under a heading nobody has chosen yet. That is not a tidiness
   * argument — a reader who has already been shown every guide in the section
   * has no reason to open a sub-section, which is the only navigation the
   * screen has.
   */
  it('shows the sub-sections and no guide list on a category that has them', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-confocal',
          slug: 'confocal',
          name: 'Confocal',
          parentId: 'c-light',
          orderIndex: 0,
        }),
      ],
      guides: [
        guideFixture({ status: 'published', title: 'Confocal startup' }),
        guideFixture({
          id: 'g-child',
          slug: 'stellaris-startup',
          title: 'Stellaris startup',
          categoryId: 'c-confocal',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Confocal$/ })).toHaveAttribute(
      'href',
      '/c/confocal',
    )
    expect(screen.queryByRole('link', { name: /Confocal startup/ })).not.toBeInTheDocument()
  })

  /* A category with nothing under it is already the bottom of the tree, so it
     is where the guides are. */
  it('shows the guides on a category with no sub-sections', async () => {
    const server = createFakeServer({
      guides: [guideFixture({ status: 'published', title: 'Confocal startup' })],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Confocal startup/ })).toHaveAttribute(
      'href',
      '/g/confocal-startup',
    )
  })

  /* The tile is a picture and a name. A count never decided which sub-section
     somebody opened. */
  it('puts no count under a sub-section', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-confocal',
          slug: 'confocal',
          name: 'Confocal',
          parentId: 'c-light',
          orderIndex: 0,
        }),
      ],
      guides: [
        guideFixture({
          id: 'g-child',
          slug: 'stellaris-startup',
          categoryId: 'c-confocal',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    const section = await screen.findByRole('link', { name: /Confocal$/ })
    expect(within(section).queryByText(/guides?$/)).toBeNull()
  })

  it('renders the landing page above the guide list, embeds and all', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({ status: 'published', title: 'Confocal startup', tags: ['stellaris'] }),
      ],
      pages: [
        pageFixture({
          id: 'w-light-landing',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          title: 'Light Microscopy',
          body: 'Book the instrument first.\n\n```guidelist\ntags: stellaris\nheading: Stellaris\n```',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByText('Book the instrument first.')).toBeInTheDocument()
    /* The embedded list is the real navigation, so it has to have resolved. */
    expect(await screen.findByRole('heading', { name: 'Stellaris' })).toBeInTheDocument()
    /* The landing page's own lists are the navigation. A second, flat run of
       every guide underneath it repeats what the reader has just been given. */
    expect(
      screen.queryByRole('heading', { name: /Everything in/ }),
    ).not.toBeInTheDocument()
  })

  it('sends an author to the editor for the landing page that already exists', async () => {
    const server = createFakeServer({
      pages: [
        pageFixture({
          id: 'w-light-landing',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          body: 'Prose.',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Edit landing page/ })).toHaveAttribute(
      'href',
      '/w/w-light-landing/edit',
    )
  })

  it('creates a landing page for the category and opens it', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderCategory(server)

    await user.click(await screen.findByRole('button', { name: /Write a landing page/ }))

    expect(await screen.findByText('Editing the landing page')).toBeInTheDocument()
    const created = server.state.pages[0]
    expect(created.categoryId).toBe('c-light')
    expect(created.isLanding).toBe(true)
    expect(created.title).toBe('Light Microscopy')
  })

  /* Both sub-categories hold a published guide, so the hidden one is kept out
     for being hidden and for no other reason. */
  it('keeps hidden sub-categories out of the browse tree', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-stellaris',
          slug: 'stellaris',
          name: 'Stellaris',
          parentId: 'c-light',
        }),
        categoryFixture({
          id: 'c-holding',
          slug: 'holding',
          name: 'Tag-only guides',
          parentId: 'c-light',
          isHidden: true,
        }),
      ],
      guides: [
        guideFixture({
          id: 'g-stellaris',
          slug: 'stellaris-startup',
          categoryId: 'c-stellaris',
          status: 'published',
        }),
        guideFixture({
          id: 'g-holding',
          slug: 'las-x-basics',
          categoryId: 'c-holding',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Stellaris/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Tag-only guides/ })).not.toBeInTheDocument()
  })

  it('still opens a hidden category by its own URL', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({
          id: 'c-holding',
          slug: 'holding',
          name: 'Tag-only guides',
          isHidden: true,
        }),
      ],
      guides: [guideFixture({ categoryId: 'c-holding', status: 'published', title: 'LAS X basics' })],
    })
    renderCategory(server, 'holding')

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Tag-only guides' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('link', { name: /LAS X basics/ })).toBeInTheDocument()
  })
})

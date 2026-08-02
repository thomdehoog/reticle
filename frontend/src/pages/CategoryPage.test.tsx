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
   * A sub-section's card counts the guides inside it.
   *
   * The count used to be taken from this page's own listing, which is scoped to
   * this category and therefore holds none of a child's guides — so every
   * sub-section on every category page read "0 guides" however full it was.
   */
  it('counts the guides inside a sub-section, not the ones beside it', async () => {
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
          title: 'Stellaris startup',
          categoryId: 'c-confocal',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    const section = await screen.findByRole('link', { name: /Confocal/ })
    expect(section).toHaveAttribute('href', '/c/confocal')
    expect(within(section).getByText('1 guide')).toBeInTheDocument()
  })

  /* Sub-sections are how a reader gets to the instrument they came for. Below
     the guide lists they were the last thing on the page. */
  it('puts the sub-sections above the guides', async () => {
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
      guides: [guideFixture({ status: 'published', title: 'Confocal startup' })],
    })
    const { container } = renderCategory(server)

    await screen.findByRole('link', { name: /Confocal startup/ })
    const links = [...container.querySelectorAll('a')].map((link) => link.getAttribute('href'))
    expect(links.indexOf('/c/confocal')).toBeLessThan(links.indexOf('/g/confocal-startup'))
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

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

/**
 * Where the banner's paragraph comes from.
 *
 * Two fields can hold a section's words and only one of them is ever filled at
 * ZMB: the migration reads the vendor's category description onto the landing
 * page's `summary`, and nothing sets `Category.description` at all. The banner
 * read only the second, so every imported section showed a title on a picture
 * and no text — while the sentence ZMB had written sat one field away.
 */
describe('CategoryPage banner', () => {
  it('uses the landing page’s summary when the category has no description', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ description: '' })],
      guides: [guideFixture({ status: 'published' })],
      pages: [
        pageFixture({
          id: 'w-landing',
          slug: 'light-microscopy',
          title: 'Light Microscopy',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          summary: 'Widefield, confocal and live-cell systems.',
        }),
      ],
    })
    renderCategory(server)

    expect(
      await screen.findByText('Widefield, confocal and live-cell systems.'),
    ).toBeInTheDocument()
  })

  /* Otherwise editing the description in the admin screen would do nothing on
     any section that has a landing page, which is all of them. */
  it('prefers the description an administrator typed', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ description: 'What an administrator typed.' })],
      guides: [guideFixture({ status: 'published' })],
      pages: [
        pageFixture({
          id: 'w-landing',
          slug: 'light-microscopy',
          title: 'Light Microscopy',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          summary: 'What the migration brought.',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByText('What an administrator typed.')).toBeInTheDocument()
    expect(screen.queryByText('What the migration brought.')).not.toBeInTheDocument()
  })

  /* The picture follows the same fallback as the words, and deliberately so:
     taking one from the category and the other from its landing page is how a
     section ends up showing one instrument over a sentence about another. */
  it('uses the landing page’s hero when the category has no picture of its own', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ description: '', heroMediaId: null, imageUrl: null })],
      guides: [guideFixture({ status: 'published' })],
      pages: [
        pageFixture({
          id: 'w-landing',
          slug: 'light-microscopy',
          title: 'Light Microscopy',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          summary: 'Widefield, confocal and live-cell systems.',
          heroMediaId: 'm-section',
        }),
      ],
    })
    renderCategory(server)

    await screen.findByText('Widefield, confocal and live-cell systems.')
    const plate = document.querySelector('.banner__plate img')
    expect(plate).toHaveAttribute('src', '/api/media/m-section')
  })

  it('shows the title alone when neither holds anything', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ description: '' })],
      guides: [guideFixture({ status: 'published' })],
    })
    renderCategory(server)

    await screen.findByRole('heading', { level: 1, name: 'Light Microscopy' })
    expect(document.querySelector('.banner__intro')).toBeNull()
  })
})

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

  /**
   * The prose on a parent's landing page is not a duplicate of anything — it is
   * where ZMB says you need an introduction on a system before you can book it,
   * and it exists nowhere else. Only the lists are repeated at the level below,
   * so only the lists come out, together with the headings that introduced
   * them.
   */
  it('shows a parent category’s prose without the guide lists inside it', async () => {
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
          tags: ['stellaris'],
        }),
      ],
      pages: [
        pageFixture({
          id: 'w-light-landing',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          title: 'Light Microscopy',
          body: 'Bring your sample to the introduction.\n\n## Starting up\n\n```guidelist\ntags: stellaris\nheading: Stellaris\n```',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByText('Bring your sample to the introduction.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Confocal$/ })).toHaveAttribute('href', '/c/confocal')

    expect(screen.queryByRole('heading', { name: 'Stellaris' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Starting up' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Stellaris startup/ })).not.toBeInTheDocument()
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

  /**
   * An empty category is kept off the browse surfaces, not taken away. Its URL
   * is what an author follows out of the admin screen or out of the category
   * picker to put the first guide in it, so it opens, it says it is empty, and
   * it offers the page nobody has written yet.
   */
  it('still opens a category with nothing in it, and offers to fill it', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ id: 'c-cryo', slug: 'cryoem', name: 'CryoEM' })],
      guides: [],
    })
    renderCategory(server, 'cryoem')

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'CryoEM' })).toBeInTheDocument(),
    )
    expect(screen.getByText('No guides in this section yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Write a landing page/ })).toBeInTheDocument()
  })
})

import { screen, waitFor, within } from '@testing-library/react'
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

  /* The picture arrives already resolved. The server falls back to the landing
     page's hero, because the tile and the search card show the same photograph
     and a rule kept on one screen is a rule the other two do not have. */
  it('shows the picture the listing gives it', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ description: '', imageUrl: '/api/media/m-section' })],
      guides: [guideFixture({ status: 'published' })],
    })
    renderCategory(server)

    await screen.findByRole('heading', { level: 1, name: 'Light Microscopy' })
    expect(document.querySelector('.banner__plate img')).toHaveAttribute(
      'src',
      '/api/media/m-section',
    )
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

    expect(await screen.findByRole('link', { name: 'Confocal' })).toHaveAttribute(
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

    const section = await screen.findByRole('link', { name: 'Confocal' })
    expect(within(section).queryByText(/guides?$/)).toBeNull()
  })

  /**
   * The bottom of the tree lists its guides under the tags that group them.
   *
   * The tag is the heading and it is a link, because the group a reader has
   * just found useful is a page of its own — the same guides gathered from
   * every section rather than only this one.
   */
  it('lists a section’s guides under their tags', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          id: 'g-startup',
          slug: 'confocal-startup',
          status: 'published',
          title: 'Confocal startup',
          tags: ['stellaris'],
        }),
      ],
    })
    renderCategory(server)

    /* Shown with a capital, linked by the slug: the heading is a name and the
       URL is the identity, and only one of them may change. */
    expect(await screen.findByRole('heading', { name: 'Stellaris' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Stellaris' })).toHaveAttribute('href', '/t/stellaris')
    expect(screen.getByRole('link', { name: /Confocal startup/ })).toBeInTheDocument()
  })

  /**
   * The bottom of the tree lists what it holds, in two parts.
   *
   * A list of groups, and the articles are one of them, called Wikis.
   *
   * There is no wiki half and no guide half. A group is a group whatever it
   * holds, so dividing the page by content type and then grouping inside one of
   * the halves would be two arrangements of the same section for a reader to
   * reconcile.
   */
  it('gives the wiki articles a group of their own, among the tag groups', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          id: 'g-startup',
          slug: 'talos-startup',
          title: 'Talos start-up',
          status: 'published',
          tags: ['talos'],
        }),
      ],
      pages: [
        pageFixture({
          id: 'w-oil',
          slug: 'immersion-oil',
          title: 'Immersion oil',
          categoryId: 'c-light',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    const wikis = await screen.findByRole('heading', { name: 'Wikis' })
    expect(screen.getByRole('link', { name: /Immersion oil/ })).toHaveAttribute(
      'href',
      '/w/immersion-oil',
    )

    const talos = screen.getByRole('heading', { name: 'Talos' })
    expect(wikis.compareDocumentPosition(talos)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
    expect(screen.getByRole('link', { name: /Talos start-up/ })).toBeInTheDocument()

    /* No half above the groups saying which kind of thing follows. */
    expect(screen.queryByRole('heading', { name: 'Guides' })).not.toBeInTheDocument()
  })

  /* Every other group heading is a link to that tag's page. This one is not:
     `/w` is the whole institute's index, a different set from this section's
     articles, and a heading that goes somewhere else is worse than one that
     goes nowhere. */
  it('links the Wikis heading like every other group', async () => {
    const server = createFakeServer({
      guides: [],
      pages: [
        pageFixture({
          id: 'w-oil',
          slug: 'immersion-oil',
          title: 'Immersion oil',
          categoryId: 'c-light',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    const heading = await screen.findByRole('heading', { name: 'Wikis' })
    expect(heading.querySelector('a')).toHaveAttribute('href', '/w')
  })

  it('shows a section that has only wikis without saying it is empty', async () => {
    const server = createFakeServer({
      guides: [],
      pages: [
        pageFixture({
          id: 'w-oil',
          slug: 'immersion-oil',
          title: 'Immersion oil',
          categoryId: 'c-light',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Immersion oil/ })).toBeInTheDocument()
    expect(screen.queryByText('Nothing in this section yet.')).not.toBeInTheDocument()
  })

  /* The section's own front page is what the banner above is made of. Listing
     it inside the section offers the reader the page they are standing on. */
  it('keeps the landing page out of the list', async () => {
    const server = createFakeServer({
      guides: [],
      pages: [
        pageFixture({
          id: 'w-landing',
          slug: 'light-microscopy',
          title: 'Light Microscopy',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
        }),
        pageFixture({
          id: 'w-oil',
          slug: 'immersion-oil',
          title: 'Immersion oil',
          categoryId: 'c-light',
          status: 'published',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: /Immersion oil/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^Light Microscopy/ })).not.toBeInTheDocument()
  })

  /**
   * The landing page is no longer this screen.
   *
   * Its words are what the banner reads and the page keeps its address, but the
   * section body is the guides and nothing else — no prose, no embedded lists,
   * no second arrangement of the same procedures for a reader to reconcile with
   * the first. This is the rule that lets a section page be learnable and lets
   * an author never have to write one.
   */
  it('does not render the landing page’s body on the section', async () => {
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
          /* The embedded list's heading is deliberately a phrase no tag could
             produce: the guide below carries `stellaris`, so a heading of
             "Stellaris" would now be ambiguous between the landing page's
             markdown and the tag group, and the test would pass either way. */
          body:
            'Book the instrument first.\n\n' +
            '```guidelist\ntags: stellaris\nheading: From the landing page\n```',
        }),
      ],
    })
    renderCategory(server)

    await screen.findByRole('link', { name: /Confocal startup/ })
    expect(screen.queryByText('Book the instrument first.')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'From the landing page' }),
    ).not.toBeInTheDocument()
  })

  /**
   * A section with sub-sections shows those and stops.
   *
   * Not the guides underneath them, and not the landing page's prose either:
   * one kind of thing per section, decided by where it sits in the tree rather
   * than by whether anybody got round to writing a page for it.
   */
  it('shows a parent’s sub-sections and nothing else', async () => {
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
          body: 'Bring your sample to the introduction.\n\n## Starting up',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: 'Confocal' })).toHaveAttribute(
      'href',
      '/c/confocal',
    )
    expect(screen.queryByText('Bring your sample to the introduction.')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Starting up' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'stellaris' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Stellaris startup/ })).not.toBeInTheDocument()
  })

  /**
   * The section form is the route to a section's words and picture, and the
   * only one.
   *
   * "Edit landing page" used to sit at the foot of this screen, because the
   * document holding those two things was reachable from nowhere else. The form
   * reaches the same fields under the names a reader would use, so the button
   * is gone rather than left as a second way in — and this asserts its absence,
   * because a second editor for one thing is exactly what nobody notices has
   * come back.
   */
  it('offers an administrator the section form, and no route to the landing page', async () => {
    const server = createFakeServer({
      guides: [guideFixture({ status: 'published' })],
      pages: [
        pageFixture({
          id: 'w-light-landing',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
          body: 'Prose the migration brought.',
        }),
      ],
    })
    renderCategory(server)

    expect(await screen.findByRole('link', { name: 'Edit Light Microscopy' })).toHaveAttribute(
      'href',
      '/categories/c-light/edit',
    )
    expect(screen.queryByRole('link', { name: /Edit landing page/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Write a landing page/ })).not.toBeInTheDocument()
    /* The body still belongs to the landing page and is still not shown here. */
    expect(screen.queryByText('Prose the migration brought.')).not.toBeInTheDocument()
  })

  /**
   * The banner edits and does not delete.
   *
   * Deleting a section destroys everything under it, and it is done from the
   * grid, where the tile is one of several and is visibly still there
   * afterwards. Offering it from inside the section puts the most destructive
   * control in the building on the screen somebody is most often only reading,
   * and leaves them answering for a page that no longer exists.
   */
  it('offers editing from the banner and nothing that destroys anything', async () => {
    const server = createFakeServer()
    renderCategory(server)

    await screen.findByRole('link', { name: 'Edit Light Microscopy' })
    expect(screen.queryByRole('button', { name: /^Delete/ })).not.toBeInTheDocument()
    expect(document.querySelector('.banner__action--danger')).toBeNull()
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

    expect(await screen.findByRole('link', { name: 'Stellaris' })).toBeInTheDocument()
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
    /* Both halves empty, which is the only case that says nothing is here —
       a section with wikis and no guides, or the reverse, is ordinary. */
    expect(screen.getByText('Nothing in this section yet.')).toBeInTheDocument()
    /* And an administrator is offered the thing to do about it. A section with
       no sub-sections is exactly where one gets added, so the tile that makes
       one is drawn even though there is no grid of them to sit beside. */
    expect(screen.getByRole('link', { name: 'Add a section' })).toHaveAttribute(
      'href',
      '/categories/new?parent=c-cryo',
    )
  })
})

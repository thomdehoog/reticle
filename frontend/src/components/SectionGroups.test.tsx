/**
 * Arranging a section by dragging its rows between groups.
 *
 * The move is an edit to the document's tags, so what these check is what the
 * server was asked for — not that a row appeared somewhere, which a preview
 * would show just as convincingly while sending nothing.
 *
 * jsdom runs no drag: it has no `DataTransfer` and fires nothing on its own, so
 * each test plays the sequence a browser would and hands over a stub for the
 * one object the handlers touch. That makes these tests of the wiring — which
 * element answers for the move, and what it sends — which is exactly where this
 * went wrong once: committing on the row's own `dragend` looked right and could
 * not work, because showing the result unmounts the row that started the drag.
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { categoryFixture, createFakeServer, guideFixture, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { CategoryPage } from '../pages/CategoryPage'

function renderSection(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/c/:slug" element={<CategoryPage />} />
    </Routes>,
    { route: '/c/light-microscopy', fetchImpl: server.fetchImpl },
  )
}

/** Enough of a `DataTransfer` for the handlers, which only set things on it. */
function transfer() {
  return { effectAllowed: '', dropEffect: '', setData: () => {}, getData: () => '' }
}

/** The panel a group is drawn in, which is the element that answers for a drop. */
function group(tag: string): HTMLElement {
  const heading = screen.getByRole('heading', { name: tag })
  return heading.closest('section')!
}

function drag(row: HTMLElement, onto: HTMLElement) {
  const dataTransfer = transfer()
  fireEvent.dragStart(row, { dataTransfer })
  fireEvent.dragEnter(onto, { dataTransfer })
  fireEvent.dragOver(onto, { dataTransfer })
  fireEvent.drop(onto, { dataTransfer })
}

function twoGroups() {
  return createFakeServer({
    categories: [categoryFixture()],
    guides: [
      guideFixture({
        id: 'g-talos',
        slug: 'talos-startup',
        title: 'Talos start-up',
        categoryId: 'c-light',
        status: 'published',
        tags: ['talos'],
      }),
      guideFixture({
        id: 'g-nikon',
        slug: 'nikon-startup',
        title: 'Nikon start-up',
        categoryId: 'c-light',
        status: 'published',
        tags: ['nikon'],
      }),
    ],
  })
}

describe('arranging a section by dragging', () => {
  it('moves a guide into the group it is dropped on', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    drag(screen.getByRole('link', { name: /^Talos start-up/ }), group('Nikon'))

    await waitFor(() =>
      expect(server.state.guides.find((guide) => guide.id === 'g-talos')!.tags).toEqual(['nikon']),
    )
  })

  /* The point of the merged grouping: the article about the Nikon goes under
     `nikon`, beside the procedures for it. */
  it('moves a wiki the same way', async () => {
    const server = twoGroups()
    server.state.pages.push(
      pageFixture({
        id: 'w-oil',
        slug: 'immersion-oil',
        title: 'Immersion oil',
        categoryId: 'c-light',
        status: 'published',
      }),
    )
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    drag(screen.getByRole('link', { name: /^Immersion oil/ }), group('Nikon'))

    await waitFor(() =>
      expect(server.state.pages.find((page) => page.id === 'w-oil')!.tags).toEqual(['nikon']),
    )
  })

  /**
   * A guide belongs under every instrument it applies to — a fifth of ZMB's
   * corpus is in more than one group, and one LAS X procedure is in ten. Taking
   * a row out of one heading must leave it in the others, or arranging a
   * section quietly unpublishes it from nine places.
   */
  it('leaves the groups it is not being dragged out of alone', async () => {
    const server = twoGroups()
    server.state.guides = server.state.guides.map((guide) =>
      guide.id === 'g-talos' ? { ...guide, tags: ['talos', 'lasx'] } : guide,
    )
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    /* The row is on the page twice, once per group it is in — which is the
       behaviour under test, so the drag has to say which of the two it grabbed. */
    drag(within(group('Talos')).getByRole('link', { name: /^Talos start-up/ }), group('Nikon'))

    await waitFor(() =>
      expect(server.state.guides.find((guide) => guide.id === 'g-talos')!.tags).toEqual([
        'lasx',
        'nikon',
      ]),
    )
  })

  it('adds a tag to a row that was in no group at all', async () => {
    const server = twoGroups()
    server.state.guides.push(
      guideFixture({
        id: 'g-loose',
        slug: 'untagged',
        title: 'Not tagged yet',
        categoryId: 'c-light',
        status: 'published',
      }),
    )
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    drag(screen.getByRole('link', { name: /^Not tagged yet/ }), group('Nikon'))

    await waitFor(() =>
      expect(server.state.guides.find((guide) => guide.id === 'g-loose')!.tags).toEqual(['nikon']),
    )
  })

  it('shows the row in the group it would land in while the mouse is still down', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    const dataTransfer = transfer()
    fireEvent.dragStart(screen.getByRole('link', { name: /^Talos start-up/ }), { dataTransfer })
    fireEvent.dragEnter(group('Nikon'), { dataTransfer })

    expect(within(group('Nikon')).getByRole('link', { name: /^Talos start-up/ })).toBeInTheDocument()
    /* Nothing sent: the arrangement is the preview, and only letting go writes. */
    expect(server.state.guides.find((guide) => guide.id === 'g-talos')!.tags).toEqual(['talos'])
  })

  it('puts the row back when the drag leaves without being dropped', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    const dataTransfer = transfer()
    fireEvent.dragStart(screen.getByRole('link', { name: /^Talos start-up/ }), { dataTransfer })
    fireEvent.dragEnter(group('Nikon'), { dataTransfer })
    fireEvent.dragLeave(group('Nikon'), { dataTransfer, relatedTarget: document.body })

    expect(within(group('Talos')).getByRole('link', { name: /^Talos start-up/ })).toBeInTheDocument()
    expect(within(group('Nikon')).queryByRole('link', { name: /^Talos start-up/ })).toBeNull()
  })

  /* Dropping a row back where it started is not a move, and sending it would
     spend a write and a re-read on nothing. */
  it('sends nothing when a row is dropped on the group it came from', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Talos' })
    server.requests.length = 0
    drag(screen.getByRole('link', { name: /^Talos start-up/ }), group('Talos'))

    expect(server.requests.filter((request) => request.method === 'PUT')).toEqual([])
  })

  it('does not offer the drag to a reader', async () => {
    const server = twoGroups()
    server.state.user = { ...server.state.user, role: 'viewer' }
    renderSection(server)

    const row = await screen.findByRole('link', { name: /^Talos start-up/ })
    expect(row).not.toHaveAttribute('draggable', 'true')
  })
})

/**
 * Stacking the groups themselves.
 *
 * Two drags share one element here — a row dropped on a panel joins its group,
 * a panel dropped on a panel takes its place — so what these check hardest is
 * that neither can be mistaken for the other.
 */
describe('stacking a section’s groups', () => {
  /** The heading order down the page, which is the arrangement under test. */
  function stack() {
    return screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent)
  }

  it('drags a group up the page and writes the whole order down', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Talos' })
    expect(stack()).toEqual(['Nikon', 'Talos'])

    const dataTransfer = transfer()
    const lifted = group('Talos')
    fireEvent.dragStart(lifted, { dataTransfer, target: lifted })
    fireEvent.dragEnter(group('Nikon'), { dataTransfer })
    expect(stack()).toEqual(['Talos', 'Nikon'])

    fireEvent.dragEnd(lifted, { dataTransfer, target: lifted })
    await waitFor(() => expect(server.state.categories[0].tagOrder).toEqual(['talos', 'nikon']))
  })

  /**
   * The panel is draggable and the rows inside it are too, so a row's
   * `dragstart` bubbles up to the panel's handler. If that were taken for a
   * lift, dragging any row would restack the page as a side effect of moving
   * it.
   */
  it('does not take a row’s drag for a group being lifted', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    /* Both events fired on the row, which is where a browser fires them. Each
       bubbles to the panel's handlers, and it is the panel deciding they were
       not meant for it that this is about — so the row is left where it is,
       and the only thing that could have happened is a write of the order. */
    const dataTransfer = transfer()
    const row = screen.getByRole('link', { name: /^Talos start-up/ })
    fireEvent.dragStart(row, { dataTransfer })
    fireEvent.dragEnd(row, { dataTransfer })

    expect(server.requests.filter((request) => request.path.endsWith('/tag-order'))).toEqual([])
    expect(server.state.categories[0].tagOrder).toEqual([])
  })

  it('does not offer the lift to an author', async () => {
    const server = twoGroups()
    server.state.user = { ...server.state.user, role: 'author' }
    renderSection(server)

    const heading = await screen.findByRole('heading', { name: 'Talos' })
    expect(heading.closest('section')).not.toHaveAttribute('draggable', 'true')
    /* And still offers them the row, which is the right they do have. */
    expect(screen.getByRole('link', { name: /^Talos start-up/ })).toHaveAttribute(
      'draggable',
      'true',
    )
  })
})

/**
 * Working a group where it is drawn.
 *
 * The section page is where the idea arrives — rename this heading, add the
 * missing shutdown procedure, retire the stale one — and each of these used
 * to mean a detour through another screen. All of it still reduces to the
 * same primitives the rest of the app uses: a rename is retagging the rows,
 * a per-group creation is a creation plus a tag, an archive is the same
 * archive the editor offers.
 */
describe('working a group where it is drawn', () => {
  function nikonWithArticle() {
    const server = twoGroups()
    server.state.pages.push(
      pageFixture({
        id: 'w-nikon',
        slug: 'about-the-nikon',
        title: 'About the Nikon',
        categoryId: 'c-light',
        status: 'published',
        tags: ['nikon'],
      }),
    )
    return server
  }

  /* One quiet word. The rows stay the same furniture — a reader comparing the
     two kinds should not meet two designs — but "which is the background
     reading" should not require opening it. */
  it('tells an article row apart, quietly', async () => {
    renderSection(nikonWithArticle())

    const article = await screen.findByRole('link', { name: /^About the Nikon/ })
    expect(within(article).getByText('Article')).toBeInTheDocument()
    const guide = screen.getByRole('link', { name: /^Nikon start-up/ })
    expect(within(guide).queryByText('Article')).not.toBeInTheDocument()
  })

  it('renames a group by editing its heading in place', async () => {
    const user = userEvent.setup()
    const server = nikonWithArticle()
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    await user.click(screen.getByRole('button', { name: 'Rename Nikon' }))
    const field = screen.getByRole('textbox', { name: 'Group name' })
    await user.clear(field)
    await user.type(field, 'Eclipse{Enter}')

    /* Every row of the group, wiki and guide alike, now wears the new tag —
       that is all a rename is. */
    await waitFor(() =>
      expect(server.state.guides.find((g) => g.id === 'g-nikon')!.tags).toEqual(['eclipse']),
    )
    expect(server.state.pages.find((p) => p.id === 'w-nikon')!.tags).toEqual(['eclipse'])
    expect(await screen.findByRole('heading', { name: 'Eclipse' })).toBeInTheDocument()
  })

  /* A group an administrator has placed must not fall back to the bottom of
     the stack because its name changed. */
  it('keeps a renamed group in the place the section gave it', async () => {
    const user = userEvent.setup()
    const server = twoGroups()
    server.state.categories = server.state.categories.map((c) =>
      c.id === 'c-light' ? { ...c, tagOrder: ['nikon', 'talos'] } : c,
    )
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    await user.click(screen.getByRole('button', { name: 'Rename Nikon' }))
    const field = screen.getByRole('textbox', { name: 'Group name' })
    await user.clear(field)
    await user.type(field, 'Eclipse{Enter}')

    await waitFor(() =>
      expect(server.state.categories.find((c) => c.id === 'c-light')!.tagOrder).toEqual([
        'eclipse',
        'talos',
      ]),
    )
  })

  /* No dialog and no navigation: the document simply appears in the group as
     a draft row, and opening it is how it gets written. */
  it('starts a guide in the group with one click', async () => {
    const user = userEvent.setup()
    const server = twoGroups()
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    await user.click(screen.getByRole('button', { name: 'Add a guide to Nikon' }))

    await waitFor(() => {
      const made = server.state.guides.find((g) => g.title === 'New guide')
      expect(made?.categoryId).toBe('c-light')
      expect(made?.tags).toEqual(['nikon'])
      expect(made?.status).toBe('draft')
    })
    expect(
      await within(group('Nikon')).findByRole('link', { name: /^New guide/ }),
    ).toBeInTheDocument()
  })

  it('starts a page in the group with one click', async () => {
    const user = userEvent.setup()
    const server = twoGroups()
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    await user.click(screen.getByRole('button', { name: 'Add a wiki to Nikon' }))

    await waitFor(() => {
      const made = server.state.pages.find((p) => p.title === 'New page')
      expect(made?.categoryId).toBe('c-light')
      expect(made?.tags).toEqual(['nikon'])
    })
    expect(
      await within(group('Nikon')).findByRole('link', { name: /^New page/ }),
    ).toBeInTheDocument()
  })

  it('edits a row from where it is listed', async () => {
    renderSection(twoGroups())
    await screen.findByRole('heading', { name: 'Nikon' })

    expect(screen.getByRole('link', { name: 'Edit Nikon start-up' })).toHaveAttribute(
      'href',
      '/g/g-nikon/edit',
    )
  })

  it('archives a row after asking', async () => {
    const user = userEvent.setup()
    const server = twoGroups()
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    await user.click(screen.getByRole('button', { name: 'Archive Nikon start-up' }))
    await user.click(screen.getByRole('button', { name: 'Archive guide' }))

    await waitFor(() =>
      expect(server.state.guides.find((g) => g.id === 'g-nikon')!.status).toBe('archived'),
    )
  })

  /* The same split the editor's lifecycle row makes: any author may edit,
     archiving is an administrator's call — the server refuses it anyway, and a
     button that always fails is a lie. */
  it('offers no archive to an author', async () => {
    const server = twoGroups()
    server.state.user.role = 'author'
    renderSection(server)
    await screen.findByRole('heading', { name: 'Nikon' })

    expect(screen.getByRole('link', { name: 'Edit Nikon start-up' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Archive Nikon start-up' }),
    ).not.toBeInTheDocument()
  })
})

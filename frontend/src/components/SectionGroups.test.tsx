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
    drag(screen.getByRole('link', { name: /Talos start-up/ }), group('Nikon'))

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
    drag(screen.getByRole('link', { name: /Immersion oil/ }), group('Nikon'))

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
    drag(within(group('Talos')).getByRole('link', { name: /Talos start-up/ }), group('Nikon'))

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
    drag(screen.getByRole('link', { name: /Not tagged yet/ }), group('Nikon'))

    await waitFor(() =>
      expect(server.state.guides.find((guide) => guide.id === 'g-loose')!.tags).toEqual(['nikon']),
    )
  })

  it('shows the row in the group it would land in while the mouse is still down', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    const dataTransfer = transfer()
    fireEvent.dragStart(screen.getByRole('link', { name: /Talos start-up/ }), { dataTransfer })
    fireEvent.dragEnter(group('Nikon'), { dataTransfer })

    expect(within(group('Nikon')).getByRole('link', { name: /Talos start-up/ })).toBeInTheDocument()
    /* Nothing sent: the arrangement is the preview, and only letting go writes. */
    expect(server.state.guides.find((guide) => guide.id === 'g-talos')!.tags).toEqual(['talos'])
  })

  it('puts the row back when the drag leaves without being dropped', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Nikon' })
    const dataTransfer = transfer()
    fireEvent.dragStart(screen.getByRole('link', { name: /Talos start-up/ }), { dataTransfer })
    fireEvent.dragEnter(group('Nikon'), { dataTransfer })
    fireEvent.dragLeave(group('Nikon'), { dataTransfer, relatedTarget: document.body })

    expect(within(group('Talos')).getByRole('link', { name: /Talos start-up/ })).toBeInTheDocument()
    expect(within(group('Nikon')).queryByRole('link', { name: /Talos start-up/ })).toBeNull()
  })

  /* Dropping a row back where it started is not a move, and sending it would
     spend a write and a re-read on nothing. */
  it('sends nothing when a row is dropped on the group it came from', async () => {
    const server = twoGroups()
    renderSection(server)

    await screen.findByRole('heading', { name: 'Talos' })
    server.requests.length = 0
    drag(screen.getByRole('link', { name: /Talos start-up/ }), group('Talos'))

    expect(server.requests.filter((request) => request.method === 'PUT')).toEqual([])
  })

  it('does not offer the drag to a reader', async () => {
    const server = twoGroups()
    server.state.user = { ...server.state.user, role: 'viewer' }
    renderSection(server)

    const row = await screen.findByRole('link', { name: /Talos start-up/ })
    expect(row).not.toHaveAttribute('draggable', 'true')
  })
})

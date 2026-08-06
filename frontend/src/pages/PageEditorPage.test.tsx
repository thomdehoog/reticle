import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { createFakeServer, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { PageEditorPage } from './PageEditorPage'
import { PageViewPage } from './PageViewPage'

function renderEditor(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/" element={<div>Guides index</div>} />
      <Route path="/w/:id/edit" element={<PageEditorPage />} />
    </Routes>,
    { route: '/w/w-light/edit', fetchImpl: server.fetchImpl },
  )
}

describe('PageEditorPage', () => {
  it('writes a capped guide list when the author asks for one', async () => {
    const server = createFakeServer({ pages: [pageFixture()] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Insert guide list' }))
    /* Scoped to the dialog: the page itself carries tags now, so the editor
       behind it has a tag input of its own, and an unscoped query finds both. */
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText('Add a tag'), 'stellaris{Enter}')
    await user.type(screen.getByLabelText('Show at most (optional)'), '5')
    await user.click(screen.getByRole('button', { name: 'Insert' }))

    await waitFor(() =>
      expect(server.state.pages[0].body).toContain('limit: 5'),
      { timeout: 4000 },
    )
    expect(server.state.pages[0].body).toContain('tags: stellaris')
  })

  it('leaves the limit out entirely when the author does not set one', async () => {
    const server = createFakeServer({ pages: [pageFixture()] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Insert guide list' }))
    /* Scoped to the dialog: the page itself carries tags now, so the editor
       behind it has a tag input of its own, and an unscoped query finds both. */
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText('Add a tag'), 'stellaris{Enter}')
    await user.click(screen.getByRole('button', { name: 'Insert' }))

    await waitFor(
      () => expect(server.state.pages[0].body).toContain('tags: stellaris'),
      { timeout: 4000 },
    )
    expect(server.state.pages[0].body).not.toContain('limit:')
  })

  it('uploads a hero image and keeps only its identifier on the page', async () => {
    const server = createFakeServer({ pages: [pageFixture()] })
    const user = userEvent.setup()
    renderEditor(server)

    const file = new File(['bytes'], 'entrance.png', { type: 'image/png' })
    await user.upload(await screen.findByLabelText('Hero image'), file)

    await waitFor(() => expect(server.state.pages[0].heroMediaId).toBe('m-1'), { timeout: 4000 })
  })

  /**
   * `.hero-picker` is a flex row shared with the category dialog's picture
   * picker. This editor had been left with the markup from when it was a
   * stack — a bare `<img>` at `width: 100%` and a row of buttons beside it —
   * so the picture claimed the whole row, the buttons could not shrink, and
   * Remove ended up past the right edge of the window: the whole editor
   * scrolled sideways at 1440 and at 390 alike. The classes are the contract
   * that keeps the picture in a fixed box and stacks the buttons beside it.
   */
  it('shows an existing hero image in a box that cannot push the buttons off screen', async () => {
    const server = createFakeServer({ pages: [pageFixture({ heroMediaId: 'm-hero' })] })
    renderEditor(server)

    expect(await screen.findByRole('button', { name: 'Remove' })).toBeInTheDocument()

    const preview = document.querySelector('.hero-picker__preview')
    expect(preview).not.toBeNull()
    // The picture lives inside the fixed-size preview, not loose in the row.
    expect(preview?.querySelector('img')?.getAttribute('src')).toBe('/api/media/m-hero')
    expect(document.querySelector('.hero-picker > img')).toBeNull()

    // The buttons are the column the stylesheet stacks, not the old row.
    const controls = document.querySelector('.hero-picker__controls')
    expect(controls).not.toBeNull()
    expect(controls?.querySelectorAll('button')).toHaveLength(2)
  })

  it('unpublishes a page after confirmation', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ status: 'published', version: 1 })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Unpublish' }))
    await user.click(screen.getByRole('button', { name: 'Unpublish page' }))

    await waitFor(() => expect(server.state.pages[0].status).toBe('draft'))
  })

  it('archives a page and leaves the editor', async () => {
    const server = createFakeServer({ pages: [pageFixture({ status: 'published' })] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Archive' }))
    await user.click(screen.getByRole('button', { name: 'Archive page' }))

    expect(await screen.findByText('Guides index')).toBeInTheDocument()
    expect(server.state.pages[0].status).toBe('archived')
  })

  it('offers a way out when a colleague saved the page first', async () => {
    const server = createFakeServer({ pages: [pageFixture({ body: 'The current wording.' })] })
    const user = userEvent.setup()
    renderEditor(server)

    const body = await screen.findByDisplayValue('The current wording.')
    server.colleagueSavesFirst()
    await user.type(body, ' And one more thing.')

    expect(
      await screen.findByText(/Someone else saved this page while you were editing/, undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/And one more thing\./, { selector: 'pre' }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Keep my version' }))
    await waitFor(
      () => expect(server.state.pages[0].body).toBe('The current wording. And one more thing.'),
      { timeout: 4000 },
    )
  })

  it('opens a past version of the page read-only', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ status: 'published', version: 1, body: 'The current wording.' })],
      revisions: {
        'w-light': [
          {
            version: 1,
            publishedAt: '2026-07-01T09:00:00Z',
            document: pageFixture({ status: 'published', body: 'The wording as first published.' }),
          },
        ],
      },
    })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: /History/ }))
    await user.click(await screen.findByRole('button', { name: /Version 1/ }))

    expect(await screen.findByText('The wording as first published.')).toBeInTheDocument()
  })
})

describe('PageViewPage', () => {
  it('credits contributors, and keeps the provenance on the printed copy', async () => {
    const server = createFakeServer({
      pages: [
        pageFixture({
          slug: 'immersion-oil',
          title: 'Immersion oil',
          status: 'published',
          version: 3,
          publishedAt: '2026-07-01T09:00:00Z',
          viewCount: 42,
          contributors: [
            { id: 'u-thom', displayName: 'Thom de Hoog' },
            { id: 'u-eva', displayName: 'Eva Meier' },
          ],
        }),
      ],
    })
    renderWithApp(
      <Routes>
        <Route path="/w/:slug" element={<PageViewPage />} />
      </Routes>,
      { route: '/w/immersion-oil', fetchImpl: server.fetchImpl },
    )

    expect(await screen.findByText(/Written by Thom de Hoog, with Eva Meier/)).toBeInTheDocument()
    /* The view count and the version number are gone from the screen: a reader
       does nothing differently because a page has been read 42 times, and the
       version is for the revision history, which authors reach from the editor. */
    expect(screen.queryByText('42 times')).not.toBeInTheDocument()
    expect(screen.queryByText(/^3 ·/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Print/ })).toBeInTheDocument()
    /* The same provenance line a printed guide carries — a wiki page taped to a
       door is just as capable of being two years out of date. */
    expect(screen.getByText(/version 3, published/)).toBeInTheDocument()
  })
})

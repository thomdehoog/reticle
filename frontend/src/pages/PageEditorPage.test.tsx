import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'

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
    await user.type(screen.getByLabelText('Add a tag'), 'stellaris{Enter}')
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
    await user.type(screen.getByLabelText('Add a tag'), 'stellaris{Enter}')
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
  it('credits contributors and shows the version it is serving', async () => {
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

    expect(await screen.findByText('Eva Meier')).toBeInTheDocument()
    expect(screen.getByText('42 times')).toBeInTheDocument()
    expect(screen.getByText(/^3 ·/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Print/ })).toBeInTheDocument()
    /* The same provenance line a printed guide carries — a wiki page taped to a
       door is just as capable of being two years out of date. */
    expect(screen.getByText(/version 3, published/)).toBeInTheDocument()
  })
})

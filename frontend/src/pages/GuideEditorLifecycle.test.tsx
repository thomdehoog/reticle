import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import type { User } from '../domain/types'
import { createFakeServer, guideFixture, imageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { GuideEditorPage } from './GuideEditorPage'

const AUTHOR: User = {
  id: 'u-eva',
  email: 'eva@zmb.uzh.ch',
  displayName: 'Eva Meier',
  role: 'author',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

function renderEditor(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/" element={<div>Guides index</div>} />
      <Route path="/g/:id/edit" element={<GuideEditorPage />} />
    </Routes>,
    { route: '/g/g-confocal/edit', fetchImpl: server.fetchImpl },
  )
}

describe('taking a guide out of circulation', () => {
  it('unpublishes it after the author confirms, and says what that means', async () => {
    const server = createFakeServer({
      guides: [guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1 })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Unpublish' }))
    expect(screen.getByText(/It goes back to draft/)).toBeInTheDocument()

    /* Still published until the second click: the first one only asks. */
    expect(server.state.guides[0].status).toBe('published')

    await user.click(screen.getByRole('button', { name: 'Unpublish guide' }))

    await waitFor(() => expect(server.state.guides[0].status).toBe('draft'))
    expect(screen.queryByRole('button', { name: 'Unpublish' })).not.toBeInTheDocument()
  })

  it('lets the author back out of unpublishing', async () => {
    const server = createFakeServer({ guides: [guideFixture({ status: 'published' })] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Unpublish' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByText(/It goes back to draft/)).not.toBeInTheDocument()
    expect(server.state.guides[0].status).toBe('published')
  })

  it('archives it for an admin and leaves the editor', async () => {
    const server = createFakeServer({ guides: [guideFixture({ status: 'published' })] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: 'Archive' }))
    await user.click(screen.getByRole('button', { name: 'Archive guide' }))

    /* Home, not back to the guide: its own URL now answers 404 for everyone. */
    expect(await screen.findByText('Guides index')).toBeInTheDocument()
    expect(server.state.guides[0].status).toBe('archived')
  })

  it('does not offer archiving to an author', async () => {
    const server = createFakeServer({
      user: AUTHOR,
      guides: [guideFixture({ status: 'published' })],
    })
    renderEditor(server)

    expect(await screen.findByRole('button', { name: 'Unpublish' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
  })
})

describe('the revision history', () => {
  it('lists published versions and opens one read-only', async () => {
    /* Two publishes' worth of history, where the wording of step 1 changed —
       which is exactly the question the history is opened to answer. */
    const published = guideFixture({ status: 'published', version: 2 })
    const server = createFakeServer({
      guides: [published],
      revisions: {
        'g-confocal': [
          { version: 1, publishedAt: '2026-07-01T09:00:00Z', document: guideFixture() },
          {
            version: 2,
            publishedAt: '2026-07-02T09:00:00Z',
            document: guideFixture({
              steps: [
                {
                  id: 's1',
                  kind: 'step',
                  orderIndex: 0,
                  title: 'Switch on the lasers',
                  bullets: [
                    {
                      id: 'b1',
                      text: 'Turn the key to position II.',
                      color: 'black',
                      icon: null,
                      level: 0,
                    },
                  ],
                  media: [],
                  video: null,
                },
              ],
            }),
          },
        ],
      },
    })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: /History/ }))

    expect(await screen.findByRole('button', { name: /Version 2/ })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Version 1/ }))

    const snapshot = await screen.findByRole('dialog', { name: 'Published versions' })
    expect(await within(snapshot).findByText('Turn the key.')).toBeInTheDocument()
    /* Read-only by design: restoring silently would overwrite today's text. */
    expect(screen.queryByRole('button', { name: /Restore/ })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back to all versions' }))
    expect(screen.getByRole('button', { name: /Version 2/ })).toBeInTheDocument()
  })

  it('explains an empty history rather than showing a blank dialog', async () => {
    const server = createFakeServer({ guides: [guideFixture()] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.click(await screen.findByRole('button', { name: /History/ }))

    expect(await screen.findByText(/has never been published/)).toBeInTheDocument()
  })
})

describe('alt text', () => {
  it('round-trips through the ordinary document save', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          steps: [
            {
              id: 's1',
              kind: 'step',
              orderIndex: 0,
              title: 'Route to the building',
              bullets: [{ id: 'b1', text: 'Walk to Lengghalde 5.', color: 'black', icon: null, level: 0 }],
              media: [imageFixture({ id: 'm1', url: '/api/media/m1' })],
              video: null,
            },
          ],
        }),
      ],
    })
    const user = userEvent.setup()
    renderEditor(server)

    const alt = await screen.findByLabelText('Description of image 1')
    await user.type(alt, 'The entrance on Lengghalde')

    await waitFor(
      () => {
        expect(server.state.guides[0].steps[0].media[0].alt).toBe('The entrance on Lengghalde')
      },
      { timeout: 4000 },
    )
  })
})

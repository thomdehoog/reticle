import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { createFakeServer, guideFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

function renderGuide(server: ReturnType<typeof createFakeServer>) {
  return renderApp({ route: '/g/confocal-startup', server })
}

describe('GuideViewPage', () => {
  it('numbers steps for the reader regardless of stored order index', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          steps: [
            {
              id: 's1',
              orderIndex: 0,
              title: 'Mount the sample',
              bullets: [{ id: 'b1', text: 'Place it on the stage.', color: 'black', icon: null, level: 0 }],
              media: [],
            },
            {
              id: 's2',
              orderIndex: 1,
              title: 'Find focus',
              bullets: [{ id: 'b2', text: 'Use the 10x first.', color: 'black', icon: null, level: 0 }],
              media: [],
            },
          ],
        }),
      ],
    })
    renderGuide(server)

    const first = await screen.findByRole('heading', { name: /Step 1: Mount the sample/ })
    const second = screen.getByRole('heading', { name: /Step 2: Find focus/ })
    expect(first).toBeInTheDocument()
    expect(second).toBeInTheDocument()
  })

  it('shows the guide metadata a microscopist needs before starting', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          difficulty: 'very_easy',
          timeRequiredMinMinutes: 30,
          timeRequiredMaxMinutes: 90,
        }),
      ],
    })
    renderGuide(server)

    expect(await screen.findByText('Very easy')).toBeInTheDocument()
    expect(screen.getByText('30 min – 1 h 30 min')).toBeInTheDocument()
    /* Scoped to the guide: the signed-in user's name is in the header too. */
    expect(within(screen.getByRole('article')).getByText('Thom de Hoog')).toBeInTheDocument()
  })

  it('labels a caution in words, not by colour or icon alone', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          steps: [
            {
              id: 's1',
              orderIndex: 0,
              title: 'Switch on the lasers',
              bullets: [
                {
                  id: 'b1',
                  text: 'Never look into the beam path.',
                  color: 'red',
                  icon: 'caution',
                  level: 0,
                },
              ],
              media: [],
            },
          ],
        }),
      ],
    })
    renderGuide(server)

    const bullet = (await screen.findByText('Never look into the beam path.')).closest('li')
    expect(bullet).not.toBeNull()

    /* The word is the accessible signal. An icon and a colour both vanish in a
       greyscale printout taped to an instrument, and for a colour-blind reader. */
    expect(within(bullet as HTMLElement).getByText('Caution')).toBeInTheDocument()

    /* Treatment follows the kind, so a caution is red whatever colour the
       author picked — here they chose red anyway. */
    expect(bullet).toHaveClass('bullet--kind-caution')
    expect(bullet).toHaveClass('bullet--color-red')
  })

  it('renders every image attached to a step', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({
          steps: [
            {
              id: 's1',
              orderIndex: 0,
              title: 'Route to the building',
              bullets: [{ id: 'b1', text: 'Walk to Lengghalde 5.', color: 'black', icon: null, level: 0 }],
              media: [
                {
                  id: 'm1',
                  kind: 'image',
                  url: '/api/media/m1',
                  displayUrl: '/api/media/m1?size=display',
                  alt: 'Entrance',
                  width: 800,
                  height: 600,
                  annotations: [],
                },
                {
                  id: 'm2',
                  kind: 'image',
                  url: '/api/media/m2',
                  displayUrl: '/api/media/m2?size=display',
                  alt: 'Reception',
                  width: 800,
                  height: 600,
                  annotations: [],
                },
              ],
            },
          ],
        }),
      ],
    })
    renderGuide(server)

    expect(await screen.findByAltText('Entrance')).toBeInTheDocument()
    expect(screen.getByAltText('Reception')).toBeInTheDocument()
  })

  it('links each tag to the listing that gathers guides across categories', async () => {
    const server = createFakeServer({
      guides: [guideFixture({ tags: ['stellaris', 'confocal'] })],
    })
    renderGuide(server)

    expect(await screen.findByRole('link', { name: 'stellaris' })).toHaveAttribute(
      'href',
      '/t/stellaris',
    )
    expect(screen.getByRole('link', { name: 'confocal' })).toHaveAttribute('href', '/t/confocal')
  })

  it('records one read when the guide is opened, and one more for the next guide', async () => {
    const live = { status: 'published', publishedAt: '2026-07-01T09:00:00Z' } as const
    const other = guideFixture({ ...live, id: 'g-sted', slug: 'sted', title: 'STED alignment' })
    const server = createFakeServer({ guides: [guideFixture(live), other] })
    const user = userEvent.setup()
    renderGuide(server)

    await screen.findByRole('heading', { name: 'Confocal startup' })
    await waitFor(() => expect(server.count('POST', '/guides/g-confocal/view')).toBe(1))

    await user.click(screen.getByRole('link', { name: 'Light Microscopy' }))
    await user.click(await screen.findByRole('link', { name: /STED alignment/ }))
    await screen.findByRole('heading', { name: 'STED alignment' })

    await waitFor(() => expect(server.count('POST', '/guides/g-sted/view')).toBe(1))
    expect(server.count('POST', '/guides/g-confocal/view')).toBe(1)
  })

  it('reads a guide by its slug, and the editor link carries its id', async () => {
    const server = createFakeServer()
    renderGuide(server)

    expect(await screen.findByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/g/g-confocal/edit',
    )
    expect(server.count('GET', '/guides/confocal-startup')).toBe(1)
  })

  it('offers a viewer no way into the editor', async () => {
    const viewer = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
    const server = createFakeServer({
      user: viewer,
      guides: [guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z' })],
    })
    renderGuide(server)

    await screen.findByRole('heading', { name: 'Confocal startup' })
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })
})

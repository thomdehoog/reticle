import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { createFakeServer, guideFixture, imageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { GuideViewPage } from './GuideViewPage'

function renderGuide(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/g/:slug" element={<GuideViewPage />} />
    </Routes>,
    { route: '/g/confocal-startup', fetchImpl: server.fetchImpl },
  )
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
              video: null,
            },
            {
              id: 's2',
              orderIndex: 1,
              title: 'Find focus',
              bullets: [{ id: 'b2', text: 'Use the 10x first.', color: 'black', icon: null, level: 0 }],
              media: [],
              video: null,
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
    expect(screen.getByText('Thom de Hoog')).toBeInTheDocument()
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
              video: null,
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

  it('shows one image large and offers the rest as thumbnails', async () => {
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
                imageFixture({ id: 'm1', url: '/api/media/m1', alt: 'Entrance' }),
                imageFixture({ id: 'm2', url: '/api/media/m2', alt: 'Reception' }),
              ],
              video: null,
            },
          ],
        }),
      ],
    })
    renderGuide(server)

    /* The first image is the one being read; the second is reachable from the
       strip rather than competing with it for width. */
    expect(await screen.findByAltText('Entrance')).toBeInTheDocument()
    expect(screen.queryByAltText('Reception')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Show image 2: Reception' })).toBeInTheDocument()
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
})

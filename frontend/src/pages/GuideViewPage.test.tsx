import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'

import { createFakeServer, guideFixture } from '../test/fakeServer'
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
      guides: [guideFixture({ difficulty: 'very_easy', timeRequiredMinutes: 90 })],
    })
    renderGuide(server)

    expect(await screen.findByText('Very easy')).toBeInTheDocument()
    expect(screen.getByText('1 h 30 min')).toBeInTheDocument()
    expect(screen.getByText('Thom de Hoog')).toBeInTheDocument()
  })

  it('announces a caution bullet to screen readers as well as colouring it', async () => {
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
    expect(within(bullet as HTMLElement).getByText('Caution:')).toBeInTheDocument()
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
                { id: 'm1', url: '/api/media/m1', alt: 'Entrance', width: 800, height: 600 },
                { id: 'm2', url: '/api/media/m2', alt: 'Reception', width: 800, height: 600 },
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

  it('lists prerequisite guides before the first step', async () => {
    const prerequisite = guideFixture({
      id: 'g-safety',
      slug: 'laser-safety',
      title: 'Laser safety briefing',
      status: 'published',
    })
    const main = guideFixture({ prerequisiteIds: ['g-safety'] })
    const server = createFakeServer({ guides: [main, prerequisite] })
    renderGuide(server)

    expect(await screen.findByText('Before you start:')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Laser safety briefing' })).toHaveAttribute(
      'href',
      '/g/laser-safety',
    )
  })
})

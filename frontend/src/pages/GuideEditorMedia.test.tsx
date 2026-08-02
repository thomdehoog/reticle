import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { createFakeServer, guideFixture, videoFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { GuideEditorPage } from './GuideEditorPage'

function renderEditor(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/g/:id/edit" element={<GuideEditorPage />} />
    </Routes>,
    { route: '/g/g-confocal/edit', fetchImpl: server.fetchImpl },
  )
}

function stepWith(overrides: Partial<ReturnType<typeof guideFixture>['steps'][number]>) {
  return guideFixture({
    steps: [
      {
        id: 's1',
        orderIndex: 0,
        title: 'Seat the filter cube',
        bullets: [{ id: 'b1', text: 'Push until it clicks.', color: 'black', icon: null, level: 0 }],
        media: [],
        video: null,
        ...overrides,
      },
    ],
  })
}

describe('adding media to a step', () => {
  it('files an uploaded clip as the step video rather than as a fifth image', async () => {
    const server = createFakeServer({ guides: [stepWith({})] })
    const user = userEvent.setup()
    const { container } = renderEditor(server)

    await screen.findByDisplayValue('Seat the filter cube')
    const picker = container.querySelector('input[type="file"]') as HTMLInputElement
    await user.upload(picker, new File(['bytes'], 'cube.mp4', { type: 'video/mp4' }))

    await waitFor(
      () => {
        const step = server.state.guides[0].steps[0]
        expect(step.video?.kind).toBe('video')
        expect(step.media).toHaveLength(0)
      },
      { timeout: 4000 },
    )
  })

  it('lets an author describe the clip, and take it off again', async () => {
    const server = createFakeServer({
      guides: [stepWith({ video: videoFixture({ alt: '' }) })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    const alt = await screen.findByLabelText('Description of the video')
    await user.type(alt, 'Seating the filter cube')
    await waitFor(
      () => expect(server.state.guides[0].steps[0].video?.alt).toBe('Seating the filter cube'),
      { timeout: 4000 },
    )

    await user.click(screen.getByRole('button', { name: 'Remove video' }))
    await waitFor(() => expect(server.state.guides[0].steps[0].video).toBeNull(), { timeout: 4000 })
  })
})

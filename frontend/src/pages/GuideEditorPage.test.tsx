import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'

import { createFakeServer, guideFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { GuideEditorPage } from './GuideEditorPage'

const BULLET_PLACEHOLDER = 'Describe what to do…'

function renderEditor(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/g/:id/edit" element={<GuideEditorPage />} />
    </Routes>,
    { route: '/g/g-confocal/edit', fetchImpl: server.fetchImpl },
  )
}

async function bulletFields() {
  return screen.findAllByPlaceholderText(BULLET_PLACEHOLDER)
}

describe('GuideEditorPage', () => {
  it('loads the guide the author asked for', async () => {
    const server = createFakeServer()
    renderEditor(server)

    expect(await screen.findByDisplayValue('Switch on the lasers')).toBeInTheDocument()
    expect(await screen.findByDisplayValue('Turn the key.')).toBeInTheDocument()
  })

  it('starts a new bullet when the author presses Enter', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    await user.click(first)
    await user.keyboard('{Enter}')

    await waitFor(async () => expect(await bulletFields()).toHaveLength(2))

    await user.keyboard('Wait for the laser to stabilise.')
    expect(await screen.findByDisplayValue('Wait for the laser to stabilise.')).toBeInTheDocument()
  })

  it('removes an empty bullet on Backspace', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    await user.click(first)
    await user.keyboard('{Enter}')
    await waitFor(async () => expect(await bulletFields()).toHaveLength(2))

    await user.keyboard('{Backspace}')
    await waitFor(async () => expect(await bulletFields()).toHaveLength(1))
  })

  it('autosaves edits without the author pressing anything', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    await user.clear(first)
    await user.type(first, 'Turn the key to position II.')

    await waitFor(
      () => {
        const saves = server.requests.filter((request) => request.method === 'PUT')
        expect(saves.length).toBeGreaterThan(0)
        const saved = saves[saves.length - 1].body as { steps: { bullets: { text: string }[] }[] }
        expect(saved.steps[0].bullets[0].text).toBe('Turn the key to position II.')
      },
      { timeout: 4000 },
    )

    expect(await screen.findByText('All changes saved')).toBeInTheDocument()
  })

  it('refuses to publish a guide with an empty step and says which one', async () => {
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
              title: '',
              bullets: [{ id: 'b2', text: '', color: 'black', icon: null, level: 0 }],
              media: [],
              video: null,
            },
          ],
        }),
      ],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await screen.findByDisplayValue('Mount the sample')
    await user.click(screen.getByRole('button', { name: 'Publish' }))

    expect(
      await screen.findByText('Step 2 is empty — add an instruction or an image, or remove it.'),
    ).toBeInTheDocument()
    expect(server.requests.some((request) => request.path.endsWith('/publish'))).toBe(false)
  })

  it('publishes a complete guide', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    await user.click(screen.getByRole('button', { name: 'Publish' }))

    await waitFor(() =>
      expect(server.requests.some((request) => request.path === '/guides/g-confocal/publish')).toBe(
        true,
      ),
    )
    expect(server.state.guides[0].status).toBe('published')
  })

  it('warns instead of overwriting when a colleague saved first', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    server.failNextSaveWithConflict()
    await user.type(first, ' Then wait.')

    expect(
      await screen.findByText(/Someone else saved this guide while you were editing/, undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument()
  })
})

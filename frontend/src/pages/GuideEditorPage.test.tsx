import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

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
  beforeEach(() => sessionStorage.clear())

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
    server.colleagueSavesFirst()
    await user.type(first, ' Then wait.')

    expect(
      await screen.findByText(/Someone else saved this guide while you were editing/, undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument()
    /* Who and when, so the author knows whether to go and ask them. */
    expect(screen.getByText(/Eva Meier saved it at/, { selector: 'p' })).toBeInTheDocument()
    /* Never only a warning. The author's own words have to be on screen and
       selectable before either way out is offered. */
    expect(
      screen.getByText(/Turn the key\. Then wait\./, { selector: 'pre' }),
    ).toBeInTheDocument()
  })

  /**
   * Without a way to adopt the server's timestamp, a conflict is permanent: the
   * editor holds the `updatedAt` that was just rejected, so every autosave
   * after it carries the same stale value and is rejected too, for as long as
   * the tab stays open.
   */
  it('saves again after the author chooses to keep their version', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    server.colleagueSavesFirst()
    await user.type(first, ' Then wait.')

    await user.click(
      await screen.findByRole('button', { name: 'Keep my version' }, { timeout: 4000 }),
    )

    await waitFor(
      () => expect(server.state.guides[0].steps[0].bullets[0].text).toBe('Turn the key. Then wait.'),
      { timeout: 4000 },
    )
    expect(await screen.findByText('All changes saved')).toBeInTheDocument()
  })

  it('never discards what the author wrote without asking twice', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    server.colleagueSavesFirst()
    await user.type(first, ' Then wait.')

    await user.click(
      await screen.findByRole('button', { name: 'Use theirs instead' }, { timeout: 4000 }),
    )
    /* One click only arms the choice; the author's text is still there. */
    expect(screen.getByDisplayValue('Turn the key. Then wait.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Discard my version' }))
    expect(await screen.findByDisplayValue('Turn the key.')).toBeInTheDocument()
  })

  /**
   * The save fired as the editor closes has no screen left to report on, so a
   * failure there is invisible unless it is written down.
   */
  it('says so next time when the save on the way out failed', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const { unmount } = renderEditor(server)

    const [first] = await bulletFields()
    await user.click(first)
    server.colleagueSavesFirst()
    await user.keyboard('!')
    unmount()

    await waitFor(() =>
      expect(sessionStorage.getItem('reticle.failed-save.g-confocal')).not.toBeNull(),
    )

    renderEditor(server)
    expect(
      await screen.findByText(/Your last change to this guide did not save/),
    ).toBeInTheDocument()
  })
})

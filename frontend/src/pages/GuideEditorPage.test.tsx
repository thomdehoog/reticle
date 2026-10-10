import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Guide } from '../domain/types'
import { guideKeys } from '../queries/guides'
import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  userFixture,
} from '../test/fakeServer'
import { renderApp } from '../test/harness'

const BULLET_PLACEHOLDER = 'Describe what to do…'

function renderEditor(server: ReturnType<typeof createFakeServer>) {
  return renderApp({ route: '/g/g-confocal/edit', server })
}

async function bulletFields() {
  return screen.findAllByPlaceholderText(BULLET_PLACEHOLDER)
}

const PUBLISHED = guideFixture({
  status: 'published',
  publishedAt: '2026-07-01T09:00:00Z',
  version: 1,
})

function saves(server: ReturnType<typeof createFakeServer>) {
  return server.requests
    .filter((request) => request.method === 'PUT')
    .map((request) => request.body as Guide & { expectedUpdatedAt: string })
}

afterEach(() => vi.restoreAllMocks())

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
            },
            {
              id: 's2',
              orderIndex: 1,
              title: '',
              bullets: [{ id: 'b2', text: '', color: 'black', icon: null, level: 0 }],
              media: [],
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

  it('offers the colleague\'s version after a conflict, and carries on from it', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    server.editGuideElsewhere('g-confocal', { title: 'Confocal startup (revised)' })
    await user.type(first, ' Then wait.')

    await screen.findByText(/Someone else saved this guide while you were editing/, undefined, {
      timeout: 4000,
    })
    /* Nothing of theirs was overwritten. */
    expect(server.state.guides[0].title).toBe('Confocal startup (revised)')
    expect(server.state.guides[0].steps[0].bullets[0].text).toBe('Turn the key.')

    await user.click(screen.getByRole('button', { name: 'Reload their version' }))

    expect(await screen.findByDisplayValue('Confocal startup (revised)')).toBeInTheDocument()
    expect(screen.queryByText(/Someone else saved this guide/)).not.toBeInTheDocument()

    /* And the next edit saves cleanly against the version just loaded. */
    await user.type(screen.getByLabelText('Summary'), 'Daily startup.')
    await waitFor(() => expect(server.state.guides[0].summary).toBe('Daily startup.'), {
      timeout: 4000,
    })
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('carries the timestamp of its own last save, so it never conflicts with itself', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    await user.type(first, ' One.')
    await waitFor(() => expect(saves(server)).toHaveLength(1), { timeout: 4000 })
    await screen.findByText('All changes saved')

    await user.type(first, ' Two.')
    await waitFor(() => expect(saves(server)).toHaveLength(2), { timeout: 4000 })

    const [one, two] = saves(server)
    expect(one.expectedUpdatedAt).toBe('2026-07-01T08:00:00Z')
    expect(two.expectedUpdatedAt).toBe('2026-07-01T08:01:00Z')
    expect(await screen.findByText('All changes saved')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not let anything fetched in the background replace unsaved typing', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const { app } = renderEditor(server)

    const [first] = await bulletFields()
    await user.type(first, ' Unsaved words.')

    /* Everything a background refresh could do: the cached copy is replaced,
       every query is declared stale, and the window regains focus. */
    server.editGuideElsewhere('g-confocal', { title: 'Changed behind the editor' })
    app.queryClient.setQueryData(guideKeys.detail('g-confocal'), server.state.guides[0])
    await app.queryClient.invalidateQueries()
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await new Promise((resolve) => setTimeout(resolve, 100))

    expect(first).toHaveValue('Turn the key. Unsaved words.')
    expect(screen.getByLabelText('Title')).toHaveValue('Confocal startup')
    /* The document itself was fetched once, when the editor opened. */
    expect(server.count('GET', '/guides/g-confocal')).toBe(1)
  })

  it('saves what was typed when the author leaves before the autosave fires', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    const [first] = await bulletFields()
    await user.type(first, ' Typed and gone.')
    await user.click(screen.getByRole('link', { name: 'Guides' }))

    await screen.findByRole('heading', { name: 'Guides' })
    await waitFor(() =>
      expect(server.state.guides[0].steps[0].bullets[0].text).toBe('Turn the key. Typed and gone.'),
    )
  })

  it('asks before leaving with changes the server has refused, and stays on a no', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderEditor(server)

    const [first] = await bulletFields()
    server.editGuideElsewhere('g-confocal', { title: 'Confocal startup (revised)' })
    await user.type(first, ' Then wait.')
    await screen.findByText(/Someone else saved this guide while you were editing/, undefined, {
      timeout: 4000,
    })

    await user.click(screen.getByRole('link', { name: 'Guides' }))
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
    expect(screen.getByDisplayValue('Turn the key. Then wait.')).toBeInTheDocument()

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('link', { name: 'Guides' }))
    await screen.findByRole('heading', { name: 'Guides' })
    /* Leaving discarded the local copy; it did not push it over the colleague's. */
    expect(server.state.guides[0].steps[0].bullets[0].text).toBe('Turn the key.')
  })

  it('opens on the server\'s current copy every time, not one remembered from before', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    await user.click(screen.getByRole('link', { name: 'Guides' }))
    await screen.findByRole('heading', { name: 'Your unpublished guides' })

    server.editGuideElsewhere('g-confocal', { summary: 'Rewritten while you were away.' })
    await user.click(screen.getByRole('link', { name: /Confocal startup/ }))

    expect(await screen.findByDisplayValue('Rewritten while you were away.')).toBeInTheDocument()
    expect(server.count('GET', '/guides/g-confocal')).toBe(2)
  })

  it('uploads an image into the step it was dropped on', async () => {
    const server = createFakeServer()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    const file = new File(['png'], 'key.png', { type: 'image/png' })
    const picker = document.querySelector('.media-slots input[type="file"]') as HTMLInputElement
    fireEvent.change(picker, { target: { files: [file] } })

    expect(await screen.findByRole('button', { name: 'Annotate image' })).toBeInTheDocument()
    await waitFor(() => expect(server.state.guides[0].steps[0].media).toHaveLength(1), {
      timeout: 4000,
    })
    expect(server.state.guides[0].steps[0].media[0]).toMatchObject({ id: 'm-1', kind: 'image' })
  })

  it('goes to the published guide after publishing, where the new status shows', async () => {
    const server = createFakeServer()
    const user = userEvent.setup()
    const { location } = renderEditor(server)

    await user.type((await bulletFields())[0], ' Last-second edit.')
    await user.click(screen.getByRole('button', { name: 'Publish' }))

    expect(await screen.findByRole('heading', { name: /Step 1: Switch on the lasers/ }))
      .toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
    expect(screen.getByText('Turn the key. Last-second edit.')).toBeInTheDocument()
    expect(screen.queryByText('Draft')).not.toBeInTheDocument()
  })

  it('shows the server\'s reason when it refuses to publish, and keeps editing possible', async () => {
    const server = createFakeServer()
    const refuse = server.fetchImpl
    const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/publish')) {
        return new Response(
          JSON.stringify({ error: { code: 'validation_failed', message: 'Step 1 needs an image.' } }),
          { status: 422, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return refuse(input, init)
    }) as typeof fetch
    const user = userEvent.setup()
    renderEditor({ ...server, fetchImpl })

    await screen.findByDisplayValue('Switch on the lasers')
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    expect(await screen.findByText('Step 1 needs an image.')).toBeInTheDocument()

    /* The save that preceded the refused publish moved `updatedAt` on; the
       next autosave has to know that, or it would conflict with itself. */
    await user.type(screen.getByLabelText('Summary'), 'Still editable.')
    await waitFor(() => expect(server.state.guides[0].summary).toBe('Still editable.'), {
      timeout: 4000,
    })
    expect(screen.queryByText(/Someone else saved/)).not.toBeInTheDocument()
  })

  it('unpublishes a guide and stays in the editor', async () => {
    const server = createFakeServer({ guides: [PUBLISHED] })
    const user = userEvent.setup()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute('href', '/g/confocal-startup')

    await user.click(screen.getByRole('button', { name: 'Unpublish' }))

    await waitFor(() => expect(server.state.guides[0].status).toBe('draft'))
    expect(await screen.findByRole('button', { name: 'Publish' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'View' })).not.toBeInTheDocument()
  })

  it('archives a guide for an admin who confirms, and leaves it alone otherwise', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const server = createFakeServer({ guides: [PUBLISHED] })
    const user = userEvent.setup()
    const { location } = renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    await user.click(screen.getByRole('button', { name: 'Archive' }))
    expect(server.count('DELETE', '/guides/g-confocal')).toBe(0)

    confirm.mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Archive' }))

    await screen.findByRole('heading', { name: 'Guides' })
    expect(location()).toBe('/')
    expect(server.state.guides[0].status).toBe('archived')
    /* Nothing tried to save the retired guide on the way out. */
    expect(saves(server)).toHaveLength(0)
  })

  it('does not offer archiving to an author', async () => {
    const author = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })
    const server = createFakeServer({ user: author })
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
  })

  it('does not count editing a guide as reading it', async () => {
    const server = createFakeServer()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(server.count('POST', '/guides/g-confocal/view')).toBe(0)
  })

  it('offers hidden categories in the picker, marked as such', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-hold',
          slug: 'holding',
          name: 'Confocal - hidden guides',
          isHidden: true,
        }),
      ],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await screen.findByDisplayValue('Switch on the lasers')
    await user.selectOptions(
      screen.getByLabelText('Category'),
      await screen.findByRole('option', { name: 'Confocal - hidden guides (hidden)' }),
    )

    await waitFor(() => expect(server.state.guides[0].categoryId).toBe('c-hold'), { timeout: 4000 })
  })
})

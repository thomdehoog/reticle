import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Page } from '../domain/types'
import { createFakeServer, pageFixture, userFixture, type FakeServer } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const DRAFT = pageFixture({ status: 'draft', publishedAt: null, version: 0 })

function renderEditor(server: FakeServer) {
  return renderApp({ route: '/w/p-objectives/edit', server })
}

async function source() {
  return (await screen.findByLabelText('Page content (Markdown)')) as HTMLTextAreaElement
}

function saves(server: FakeServer): Page[] {
  return server.requests
    .filter((request) => request.method === 'PUT')
    .map((request) => request.body as Page)
}

afterEach(() => vi.restoreAllMocks())

describe('PageEditorPage', () => {
  it('loads the page into the source box and renders it in the preview', async () => {
    const server = createFakeServer({ pages: [pageFixture({ body: 'Use **oil** for the 63x.' })] })
    renderEditor(server)

    expect(await source()).toHaveValue('Use **oil** for the 63x.')
    expect(screen.getByDisplayValue('Choosing an objective')).toBeInTheDocument()

    const preview = screen.getByText('Preview').parentElement as HTMLElement
    expect(within(preview).getByText('oil').tagName).toBe('STRONG')
  })

  it('keeps the preview in step with what is typed', async () => {
    const server = createFakeServer({ pages: [DRAFT] })
    const user = userEvent.setup()
    renderEditor(server)

    const box = await source()
    await user.clear(box)
    await user.type(box, '## Cleaning')

    expect(screen.getByRole('heading', { level: 2, name: 'Cleaning' })).toBeInTheDocument()
  })

  it('autosaves the whole page with the timestamp it last saw', async () => {
    const server = createFakeServer({ pages: [DRAFT] })
    const user = userEvent.setup()
    renderEditor(server)

    await user.type(await source(), ' Then focus.')

    await waitFor(() => expect(saves(server).length).toBeGreaterThan(0), { timeout: 4000 })
    const sent = saves(server)[0] as Page & { expectedUpdatedAt: string }
    expect(sent.body).toBe('Match the immersion medium to the objective. Then focus.')
    expect(sent.title).toBe('Choosing an objective')
    expect(sent.expectedUpdatedAt).toBe('2026-07-01T08:00:00Z')

    expect(await screen.findByText('All changes saved')).toBeInTheDocument()
    expect(server.state.pages[0].body).toContain('Then focus.')
  })

  it('warns instead of overwriting when a colleague saved first', async () => {
    const server = createFakeServer({ pages: [DRAFT] })
    const user = userEvent.setup()
    renderEditor(server)

    const box = await source()
    server.editPageElsewhere('p-objectives', { body: 'Rewritten by a colleague.' })
    await user.type(box, ' My addition.')

    expect(
      await screen.findByText(/Someone else saved this page while you were editing/, undefined, {
        timeout: 4000,
      }),
    ).toBeInTheDocument()
    expect(server.state.pages[0].body).toBe('Rewritten by a colleague.')

    await user.click(screen.getByRole('button', { name: 'Reload their version' }))

    await waitFor(() => expect(box).toHaveValue('Rewritten by a colleague.'))
    expect(screen.queryByText(/Someone else saved this page/)).not.toBeInTheDocument()
    expect(screen.getByText('All changes saved')).toBeInTheDocument()
  })

  it('wraps the selection when a formatting button is pressed', async () => {
    const server = createFakeServer({ pages: [pageFixture({ ...DRAFT, body: 'Use oil here.' })] })
    const user = userEvent.setup()
    renderEditor(server)

    const box = await source()
    box.setSelectionRange(4, 7)
    await user.click(screen.getByRole('button', { name: 'Bold' }))

    expect(box).toHaveValue('Use **oil** here.')
  })

  it('inserts a guide list built from the dialog', async () => {
    const server = createFakeServer({ pages: [pageFixture({ ...DRAFT, body: 'Intro.' })] })
    const user = userEvent.setup()
    renderEditor(server)

    const box = await source()
    box.setSelectionRange(6, 6)
    await user.click(screen.getByRole('button', { name: 'Insert guide list' }))

    const dialog = screen.getByRole('dialog', { name: 'Insert a guide list' })
    await user.type(within(dialog).getByLabelText('Add a tag'), 'stellaris{Enter}')
    await user.type(within(dialog).getByLabelText('Heading (optional)'), 'Stellaris 5')
    await user.click(within(dialog).getByRole('button', { name: 'Insert' }))

    expect(box).toHaveValue('Intro.\n\n```guidelist\ntags: stellaris\nheading: Stellaris 5\n```\n\n')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    /* And the preview shows the list itself, not the block's source. */
    expect(await screen.findByRole('heading', { name: 'Stellaris 5' })).toBeInTheDocument()
  })

  it('uploads an image and places it in the body as Markdown', async () => {
    const server = createFakeServer({ pages: [pageFixture({ ...DRAFT, body: '' })] })
    renderEditor(server)

    const box = await source()
    const file = new File(['png'], 'objective turret.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload an image'), { target: { files: [file] } })

    await waitFor(() => expect(box).toHaveValue('![objective turret](/api/media/m-1)\n\n'))
    expect(server.count('POST', '/media')).toBe(1)
  })

  it('files the page under a category and makes it the landing page', async () => {
    const server = createFakeServer({ pages: [DRAFT] })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    const landing = screen.getByLabelText(/Use as this category/)
    expect(landing).toBeDisabled()

    await user.selectOptions(screen.getByLabelText('Category'), 'Light Microscopy')
    await user.click(landing)

    await waitFor(
      () => expect(server.state.pages[0]).toMatchObject({ categoryId: 'c-light', isLanding: true }),
      { timeout: 4000 },
    )
  })

  it('does not offer to make a second landing page for a category that has one', async () => {
    const server = createFakeServer({
      pages: [
        DRAFT,
        pageFixture({
          id: 'p-landing',
          slug: 'light-landing',
          title: 'About light microscopy',
          categoryId: 'c-light',
          isLanding: true,
        }),
      ],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.selectOptions(screen.getByLabelText('Category'), 'Light Microscopy')

    expect(await screen.findByRole('link', { name: 'About light microscopy' })).toHaveAttribute(
      'href',
      '/w/p-landing/edit',
    )
    expect(screen.getByLabelText(/Use as this category/)).toBeDisabled()
  })

  it('stops being a landing page when it is taken out of its category', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ ...DRAFT, categoryId: 'c-light', isLanding: true })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.selectOptions(screen.getByLabelText('Category'), 'Standalone article')

    expect(screen.getByLabelText(/Use as this category/)).not.toBeChecked()
    await waitFor(
      () => expect(server.state.pages[0]).toMatchObject({ categoryId: null, isLanding: false }),
      { timeout: 4000 },
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('refuses to publish an empty page, and says why', async () => {
    const server = createFakeServer({ pages: [pageFixture({ ...DRAFT, title: '', body: '  ' })] })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Publish' }))

    expect(screen.getByText('A page needs a title before it can be published.')).toBeInTheDocument()
    expect(screen.getByText('A page needs some content before it can be published.'))
      .toBeInTheDocument()
    expect(server.requests.some((request) => request.path.endsWith('/publish'))).toBe(false)
  })

  it('publishes what is on screen and goes to the published page', async () => {
    const server = createFakeServer({ pages: [DRAFT] })
    const user = userEvent.setup()
    const { location } = renderEditor(server)

    await user.type(await source(), ' Final sentence.')
    /* Straight away, before the autosave has had its 1.2 seconds. */
    await user.click(screen.getByRole('button', { name: 'Publish' }))

    expect(await screen.findByRole('article')).toBeInTheDocument()
    expect(location()).toBe('/w/choosing-an-objective')
    expect(server.state.pages[0]).toMatchObject({ status: 'published', version: 1 })
    expect(server.state.pages[0].body).toContain('Final sentence.')
    expect(screen.getByText(/Final sentence\./)).toBeInTheDocument()
  })

  it('unpublishes a page and stays in the editor', async () => {
    const server = createFakeServer({ pages: [pageFixture()] })
    const user = userEvent.setup()
    const { location } = renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Unpublish' }))

    await waitFor(() => expect(server.state.pages[0].status).toBe('draft'))
    expect(await screen.findByText('Draft')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Unpublish' })).not.toBeInTheDocument()
    expect(location()).toBe('/w/p-objectives/edit')
  })

  it('lets an admin archive the page, after asking', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const server = createFakeServer({ pages: [pageFixture()] })
    const user = userEvent.setup()
    const { location } = renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Archive' }))

    expect(confirm).toHaveBeenCalled()
    await screen.findByRole('heading', { name: 'Guides' })
    expect(location()).toBe('/')
    expect(server.state.pages[0].status).toBe('archived')
    expect(screen.queryByText('Choosing an objective')).not.toBeInTheDocument()
  })

  it('does not offer archiving to an author', async () => {
    const server = createFakeServer({ user: AUTHOR, pages: [pageFixture()] })
    renderEditor(server)

    await source()
    expect(screen.queryByRole('button', { name: 'Archive' })).not.toBeInTheDocument()
  })

  it('does not count editing a page as reading it', async () => {
    const server = createFakeServer({ pages: [pageFixture()] })
    renderEditor(server)

    await source()
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(server.count('POST', '/pages/p-objectives/view')).toBe(0)
  })
})

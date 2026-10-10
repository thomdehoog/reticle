/**
 * Saving is not publishing, on every screen that could confuse the two.
 *
 * The promise is that editing a published guide never changes what readers
 * have until the author publishes. The server keeps it; these tests are about
 * the screens telling the truth about it — a reader page that shows what
 * readers see, an editor that says readers do not have the changes yet, and a
 * way to see, publish or throw away what is pending.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PDF_ATTEMPTS } from '../hooks/usePdfDownload'
import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  pageFixture,
  userFixture,
  type FakeServer,
} from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })
const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const PUBLISHED = guideFixture({
  status: 'published',
  publishedAt: '2026-07-01T09:00:00Z',
  version: 3,
  title: 'Confocal startup',
  tags: ['stellaris'],
})

const PAGE = pageFixture({ body: 'Use **oil** for the 63x.', version: 2 })

/** A published guide whose working copy an author has since edited. */
function withPendingGuideEdit(user = AUTHOR): FakeServer {
  const server = createFakeServer({ user, guides: [PUBLISHED], pages: [] })
  server.editGuideElsewhere(PUBLISHED.id, {
    title: 'Confocal startup, rewritten',
    steps: [
      {
        ...PUBLISHED.steps[0],
        bullets: [{ id: 'b1', text: 'Press the new button.', color: 'black', icon: null, level: 0 }],
      },
    ],
  })
  return server
}

function withPendingPageEdit(user = AUTHOR): FakeServer {
  const server = createFakeServer({ user, guides: [], pages: [PAGE] })
  server.editPageElsewhere(PAGE.id, { body: 'Use glycerol for everything.' })
  return server
}

function requestsFor(server: FakeServer, path: string) {
  return server.requests.filter((request) => request.path === path)
}

afterEach(() => vi.restoreAllMocks())

describe('the guide reader', () => {
  it('shows a viewer the published version and no hint that anything is pending', async () => {
    const server = withPendingGuideEdit(VIEWER)
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(screen.getByText('Turn the key.')).toBeInTheDocument()
    expect(screen.queryByText('Press the new button.')).not.toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Preview changes' })).not.toBeInTheDocument()
    /* One request: a viewer is simply sent the right thing. */
    expect(requestsFor(server, '/guides/confocal-startup')).toHaveLength(1)
  })

  it('shows an author what readers see, and says that newer work exists', async () => {
    const server = withPendingGuideEdit()
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(screen.getByText('Turn the key.')).toBeInTheDocument()
    expect(screen.queryByText('Press the new button.')).not.toBeInTheDocument()

    const notice = screen.getByText(/This guide has unpublished changes/).closest('[role="note"]')
    expect(notice).toHaveTextContent('Readers see version 3')
    expect(within(notice as HTMLElement).getByRole('link', { name: 'Preview changes' })).toHaveAttribute(
      'href',
      '/g/confocal-startup?preview=true',
    )
    expect(within(notice as HTMLElement).getByRole('link', { name: 'Edit' })).toHaveAttribute(
      'href',
      '/g/g-confocal/edit',
    )

    const asked = requestsFor(server, '/guides/confocal-startup').map((r) => r.query.get('view'))
    expect(asked).toEqual([null, 'published'])
  })

  it('previews the working copy in the reader, bannered as not what readers have', async () => {
    const server = withPendingGuideEdit()
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('link', { name: 'Preview changes' }))

    expect(
      await screen.findByRole('heading', { name: 'Confocal startup, rewritten' }),
    ).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup?preview=true')
    expect(screen.getByText('Press the new button.')).toBeInTheDocument()
    expect(screen.queryByText('Turn the key.')).not.toBeInTheDocument()

    const banner = screen.getByText(/Preview of unpublished changes/).closest('[role="note"]')
    expect(banner).toHaveTextContent('readers still see version 3')
    expect(banner).toHaveClass('revision-banner')
    expect(screen.queryByText(/This guide has unpublished changes/)).not.toBeInTheDocument()

    await user.click(within(banner as HTMLElement).getByRole('link', { name: 'Back to what readers see' }))

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
    expect(screen.getByText('Turn the key.')).toBeInTheDocument()
  })

  it('opens straight on the preview from a link that asks for it', async () => {
    const server = withPendingGuideEdit()
    renderApp({ route: '/g/confocal-startup?preview=true', server })

    expect(
      await screen.findByRole('heading', { name: 'Confocal startup, rewritten' }),
    ).toBeInTheDocument()
    /* Nothing needed the published version, so it was not fetched. */
    expect(
      requestsFor(server, '/guides/confocal-startup').map((r) => r.query.get('view')),
    ).toEqual([null])
  })

  it('ignores a preview request when there is nothing to preview', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED] })
    renderApp({ route: '/g/confocal-startup?preview=true', server })

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(screen.queryByText(/Preview of unpublished changes/)).not.toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
    expect(requestsFor(server, '/guides/confocal-startup')).toHaveLength(1)
  })

  it('gives a viewer the published version even when the address asks for a preview', async () => {
    const server = withPendingGuideEdit(VIEWER)
    renderApp({ route: '/g/confocal-startup?preview=true', server })

    expect(await screen.findByRole('heading', { name: 'Confocal startup' })).toBeInTheDocument()
    expect(screen.queryByText('Press the new button.')).not.toBeInTheDocument()
  })

  it('opens a draft that was never published as the working copy, with the draft notice', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [guideFixture()] })
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByText(/This guide is a draft/)).toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
    expect(requestsFor(server, '/guides/confocal-startup')).toHaveLength(1)
  })

  it('falls back to the working copy, labelled, if the published one has just gone', async () => {
    const server = withPendingGuideEdit()
    const fetchImpl = server.fetchImpl
    /* Unpublished by a colleague between the two requests. */
    server.fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).includes('view=published')) {
        return new Response(JSON.stringify({ error: { code: 'not_found', message: 'Not found.' } }), {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        })
      }
      return fetchImpl(input, init)
    }) as typeof fetch
    renderApp({ route: '/g/confocal-startup', server })

    expect(
      await screen.findByRole('heading', { name: 'Confocal startup, rewritten' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/Preview of unpublished changes/)).toBeInTheDocument()
  })
})

describe('lists', () => {
  it('mark a guide whose working copy is ahead, for authors', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED], pages: [PAGE] })
    server.editGuideElsewhere(PUBLISHED.id, { title: 'Confocal startup, rewritten' })
    renderApp({ route: '/t/stellaris', server })

    /* An author's list is of working copies: that is the title they typed. */
    const row = (await screen.findByRole('link', { name: 'Confocal startup, rewritten' })).closest(
      '.guide-row',
    )
    expect(row).toHaveTextContent('Unpublished changes')
    expect(row?.querySelector('.badge--changes')).not.toBeNull()
  })

  it('show a viewer the published title and no badge', async () => {
    const server = withPendingGuideEdit(VIEWER)
    renderApp({ route: '/t/stellaris', server })

    const row = (await screen.findByRole('link', { name: 'Confocal startup' })).closest('.guide-row')
    expect(row).not.toHaveTextContent('Unpublished changes')
    expect(screen.queryByRole('link', { name: /rewritten/ })).not.toBeInTheDocument()
  })

  it('do not badge a published guide that has nothing pending', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED] })
    renderApp({ route: '/t/stellaris', server })

    const row = (await screen.findByRole('link', { name: 'Confocal startup' })).closest('.guide-row')
    expect(row).not.toHaveTextContent('Unpublished changes')
  })

  it('mark a wiki page in the wiki index', async () => {
    const server = withPendingPageEdit()
    renderApp({ route: '/wiki', server })

    const row = (await screen.findByRole('link', { name: 'Choosing an objective' })).closest(
      '.guide-row',
    )
    expect(row).toHaveTextContent('Unpublished changes')
  })
})

describe('the guide editor', () => {
  const edit = (server: FakeServer) => renderApp({ route: '/g/g-confocal/edit', server })

  it('says readers have this version, and offers nothing to publish or discard, when nothing changed', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED] })
    edit(server)

    expect(await screen.findByText('Readers see this version (3)')).toBeInTheDocument()
    const publish = screen.getByRole('button', { name: 'Publish update' })
    expect(publish).toBeDisabled()
    expect(publish).toHaveAttribute('title', 'There are no changes to publish.')
    expect(screen.queryByRole('button', { name: 'Discard changes' })).not.toBeInTheDocument()
  })

  it('says readers still see the old version as soon as something is typed, and after it is saved', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED] })
    const user = userEvent.setup()
    edit(server)

    await user.type(await screen.findByDisplayValue('Turn the key.'), ' Then wait.')

    /* At once — "All changes saved" must never be read as "readers have it". */
    expect(
      screen.getByText('Unpublished changes — readers still see version 3'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish update' })).toBeEnabled()

    await waitFor(() => expect(server.saveCount).toBeGreaterThan(0), { timeout: 4000 })
    await screen.findByText('All changes saved')
    expect(
      screen.getByText('Unpublished changes — readers still see version 3'),
    ).toBeInTheDocument()
    expect(server.state.guides[0].status).toBe('published')
    expect(server.state.guides[0].version).toBe(3)
  })

  it('opens on a guide with pending changes already saying so', async () => {
    const server = withPendingGuideEdit()
    edit(server)

    expect(
      await screen.findByText('Unpublished changes — readers still see version 3'),
    ).toBeInTheDocument()
    expect(screen.getByDisplayValue('Press the new button.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Discard changes' })).toBeEnabled()
  })

  it('does not talk about readers at all for a draft', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [guideFixture()] })
    edit(server)

    await screen.findByDisplayValue('Turn the key.')
    expect(screen.queryByText(/Readers see|readers still see/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Discard changes' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeEnabled()
  })

  it('discards the changes after asking, and puts the published version back in the editor', async () => {
    const server = withPendingGuideEdit()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    edit(server)

    await user.click(await screen.findByRole('button', { name: 'Discard changes' }))

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(confirm.mock.calls[0][0]).toContain('since version 3 was published')
    expect(confirm.mock.calls[0][0]).toContain('cannot be undone')

    expect(await screen.findByDisplayValue('Turn the key.')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('Press the new button.')).not.toBeInTheDocument()
    expect(screen.getByDisplayValue('Confocal startup')).toBeInTheDocument()
    expect(await screen.findByText('Readers see this version (3)')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Discard changes' })).not.toBeInTheDocument()

    expect(server.count('POST', '/guides/g-confocal/revert')).toBe(1)
    expect(server.state.guides[0].title).toBe('Confocal startup')
    expect(server.state.guides[0].version).toBe(3)
  })

  it('does nothing when the author thinks better of it', async () => {
    const server = withPendingGuideEdit()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    edit(server)

    await user.click(await screen.findByRole('button', { name: 'Discard changes' }))

    expect(server.count('POST', '/guides/g-confocal/revert')).toBe(0)
    expect(screen.getByDisplayValue('Press the new button.')).toBeInTheDocument()
  })

  it('throws away what was typed and not yet saved, without saving it first', async () => {
    const server = createFakeServer({ user: AUTHOR, guides: [PUBLISHED] })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    edit(server)

    await user.type(await screen.findByDisplayValue('Turn the key.'), ' Typed and regretted.')
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))

    expect(await screen.findByDisplayValue('Turn the key.')).toBeInTheDocument()
    await waitFor(() => expect(server.count('POST', '/guides/g-confocal/revert')).toBe(1))
    /* Long enough for a forgotten autosave to have fired. */
    await new Promise((resolve) => setTimeout(resolve, 1500))
    expect(server.count('PUT', '/guides/g-confocal')).toBe(0)
    expect(screen.getByDisplayValue('Turn the key.')).toBeInTheDocument()
  }, 10_000)

  it('keeps working after a discard: the next edit saves against the restored copy', async () => {
    const server = withPendingGuideEdit()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    edit(server)

    await user.click(await screen.findByRole('button', { name: 'Discard changes' }))
    await user.type(await screen.findByDisplayValue('Turn the key.'), ' Slowly.')

    await waitFor(() => expect(server.count('PUT', '/guides/g-confocal')).toBe(1), { timeout: 4000 })
    await screen.findByText('All changes saved')
    expect(screen.queryByText(/Someone else saved/)).not.toBeInTheDocument()
    expect(server.state.guides[0].steps[0].bullets[0].text).toBe('Turn the key. Slowly.')
  })

  it('shows the reason when the server will not discard', async () => {
    const server = withPendingGuideEdit()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const fetchImpl = server.fetchImpl
    server.fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).endsWith('/revert')) {
        return new Response(
          JSON.stringify({ error: { code: 'conflict', message: 'It was unpublished a moment ago.' } }),
          { status: 409, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return fetchImpl(input, init)
    }) as typeof fetch
    const user = userEvent.setup()
    edit(server)

    await user.click(await screen.findByRole('button', { name: 'Discard changes' }))

    expect(await screen.findByText('It was unpublished a moment ago.')).toBeInTheDocument()
  })

  it('publishes the changes, after which the reader shows them to everyone with no notice', async () => {
    const server = withPendingGuideEdit()
    const user = userEvent.setup()
    const { location } = edit(server)

    await user.click(await screen.findByRole('button', { name: 'Publish update' }))

    expect(
      await screen.findByRole('heading', { name: 'Confocal startup, rewritten' }),
    ).toBeInTheDocument()
    expect(location()).toBe('/g/confocal-startup')
    expect(screen.getByText('Press the new button.')).toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
    expect(server.state.guides[0].version).toBe(4)
  })
})

describe('the wiki', () => {
  it('shows an author the published page, with the way to the pending changes', async () => {
    const server = withPendingPageEdit()
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/w/choosing-an-objective', server })

    expect(await screen.findByText('oil')).toBeInTheDocument()
    expect(screen.queryByText('Use glycerol for everything.')).not.toBeInTheDocument()
    expect(screen.getByText(/This page has unpublished changes/).closest('[role="note"]')).toHaveTextContent(
      'Readers see version 2',
    )

    await user.click(screen.getByRole('link', { name: 'Preview changes' }))

    expect(await screen.findByText('Use glycerol for everything.')).toBeInTheDocument()
    expect(location()).toBe('/w/choosing-an-objective?preview=true')
    expect(screen.getByText(/Preview of unpublished changes/)).toBeInTheDocument()
  })

  it('shows a viewer the published page only', async () => {
    const server = withPendingPageEdit(VIEWER)
    renderApp({ route: '/w/choosing-an-objective?preview=true', server })

    expect(await screen.findByText('oil')).toBeInTheDocument()
    expect(screen.queryByText('Use glycerol for everything.')).not.toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
  })

  it('discards a page\'s changes from its editor', async () => {
    const server = withPendingPageEdit()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    renderApp({ route: '/w/p-objectives/edit', server })

    expect(
      await screen.findByText('Unpublished changes — readers still see version 2'),
    ).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Discard changes' }))

    await waitFor(() =>
      expect(screen.getByLabelText('Page content (Markdown)')).toHaveValue('Use **oil** for the 63x.'),
    )
    expect(server.count('POST', '/pages/p-objectives/revert')).toBe(1)
    expect(await screen.findByText('Readers see this version (2)')).toBeInTheDocument()
  })
})

describe('a category landing page', () => {
  const LIGHT = categoryFixture()
  const LANDING = pageFixture({
    id: 'p-landing',
    slug: 'light-microscopy-landing',
    title: 'Light microscopy',
    categoryId: 'c-light',
    isLanding: true,
    body: 'Start here if you are new to the facility.',
    version: 4,
  })

  function server(user = AUTHOR) {
    const fake = createFakeServer({ user, categories: [LIGHT], guides: [], pages: [LANDING] })
    fake.editPageElsewhere(LANDING.id, { body: 'A rewrite nobody has published.' })
    return fake
  }

  it('shows an author the landing page readers have, and that it has pending changes', async () => {
    renderApp({ route: '/c/light-microscopy', server: server() })

    expect(await screen.findByText('Start here if you are new to the facility.')).toBeInTheDocument()
    expect(screen.queryByText('A rewrite nobody has published.')).not.toBeInTheDocument()
    const notice = screen.getByText(/This landing page has unpublished changes/).closest('[role="note"]')
    expect(notice).toHaveTextContent('Readers see version 4')
    expect(within(notice as HTMLElement).getByRole('link', { name: 'Preview changes' })).toHaveAttribute(
      'href',
      '/w/light-microscopy-landing?preview=true',
    )
  })

  it('shows a viewer the same landing page without the notice', async () => {
    renderApp({ route: '/c/light-microscopy', server: server(VIEWER) })

    expect(await screen.findByText('Start here if you are new to the facility.')).toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
  })

  it('still shows an author a landing page that is only a draft, labelled as one', async () => {
    const fake = createFakeServer({
      user: AUTHOR,
      categories: [LIGHT],
      guides: [],
      pages: [{ ...LANDING, status: 'draft', publishedAt: null, version: 0 }],
    })
    renderApp({ route: '/c/light-microscopy', server: fake })

    expect(await screen.findByText('Start here if you are new to the facility.')).toBeInTheDocument()
    expect(screen.getByText('The landing page below is a draft.')).toBeInTheDocument()
    expect(screen.queryByText(/unpublished changes/i)).not.toBeInTheDocument()
  })

  it('says so when a published page has been made the landing page here but not yet published as one', async () => {
    const fake = createFakeServer({
      user: AUTHOR,
      categories: [LIGHT],
      guides: [],
      pages: [{ ...LANDING, isLanding: false }],
    })
    fake.editPageElsewhere(LANDING.id, { isLanding: true })
    renderApp({ route: '/c/light-microscopy', server: fake })

    expect(
      await screen.findByText('The landing page below is not published here yet.'),
    ).toBeInTheDocument()
  })
})

describe('the PDF button', () => {
  function captureDownloads() {
    const saved: { name: string; blob: Blob }[] = []
    const blobs = new Map<string, Blob>()
    URL.createObjectURL = vi.fn((blob: Blob) => {
      const url = `blob:reticle/${blobs.size + 1}`
      blobs.set(url, blob)
      return url
    })
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      const blob = blobs.get(this.href)
      if (blob) saved.push({ name: this.download, blob })
    })
    return saved
  }

  it('fetches the published version and hands the file to the browser under the guide\'s name', async () => {
    const saved = captureDownloads()
    const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(saved[0].name).toBe('confocal-startup.pdf')
    expect(await saved[0].blob.text()).toBe('%PDF-1.4 Confocal startup v3')
    const [request] = requestsFor(server, '/guides/confocal-startup/pdf')
    expect(request.query.get('view')).toBe('published')
    expect(await screen.findByRole('button', { name: 'PDF' })).toBeEnabled()
  })

  it('downloads the version on screen: published by default, the working copy in a preview', async () => {
    const saved = captureDownloads()
    const server = withPendingGuideEdit()
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))
    await waitFor(() => expect(saved).toHaveLength(1))
    expect(await saved[0].blob.text()).toBe('%PDF-1.4 Confocal startup v3')

    await user.click(screen.getByRole('link', { name: 'Preview changes' }))
    await screen.findByText(/Preview of unpublished changes/)
    await user.click(screen.getByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(saved).toHaveLength(2))
    expect(await saved[1].blob.text()).toBe('%PDF-1.4 Confocal startup, rewritten v3')
    expect(
      requestsFor(server, '/guides/confocal-startup/pdf').map((r) => r.query.get('view')),
    ).toEqual(['published', null])
  })

  it('waits and asks again when the server is busy, and says so meanwhile', async () => {
    const saved = captureDownloads()
    const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
    server.busyPdfFor(2, '0')
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))

    await waitFor(() => expect(saved).toHaveLength(1))
    expect(requestsFor(server, '/guides/confocal-startup/pdf')).toHaveLength(3)
    expect(screen.queryByText(/busy/)).not.toBeInTheDocument()
  })

  it('shows "Preparing PDF…" and the server\'s words while it waits', async () => {
    captureDownloads()
    const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
    server.busyPdfFor(1, '30')
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))

    expect(await screen.findByRole('button', { name: 'Preparing PDF…' })).toBeDisabled()
    const status = await screen.findByText(/The server is busy preparing other PDF exports/)
    expect(status).toHaveTextContent('Trying again shortly…')
    expect(status.closest('[role="status"]')).not.toBeNull()
    /* It is waiting the thirty seconds it was asked to, not hammering. */
    expect(requestsFor(server, '/guides/confocal-startup/pdf')).toHaveLength(1)
  })

  it('gives up politely after a few tries rather than waiting for ever', async () => {
    const saved = captureDownloads()
    const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
    server.busyPdfFor(100, '0')
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))

    expect(await screen.findByText(/still busy preparing other PDFs/)).toHaveTextContent(
      'Nothing is wrong with this guide',
    )
    expect(requestsFor(server, '/guides/confocal-startup/pdf')).toHaveLength(PDF_ATTEMPTS)
    expect(saved).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'PDF' })).toBeEnabled()
  })

  it('reports any other failure in the server\'s words, and never saves it as a file', async () => {
    const saved = captureDownloads()
    const server = createFakeServer({ user: VIEWER, guides: [PUBLISHED] })
    const fetchImpl = server.fetchImpl
    server.fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
      if (String(input).includes('/pdf')) {
        return new Response(
          JSON.stringify({ error: { code: 'not_found', message: 'That guide does not exist.' } }),
          { status: 404, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return fetchImpl(input, init)
    }) as typeof fetch
    const user = userEvent.setup()
    renderApp({ route: '/g/confocal-startup', server })

    await user.click(await screen.findByRole('button', { name: 'PDF' }))

    expect(await screen.findByText('That guide does not exist.')).toBeInTheDocument()
    expect(saved).toHaveLength(0)
  })
})

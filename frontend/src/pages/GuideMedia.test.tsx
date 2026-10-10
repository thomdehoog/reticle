/**
 * Step media end to end: pictures and videos in the reader, and getting them
 * into a step in the editor — progress, refusals and all.
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { UploadProgress, UploadTransport } from '../api/client'
import { MAX_VIDEO_BYTES } from '../domain/media'
import type { Guide, Media } from '../domain/types'
import { createFakeServer, guideFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })

const image = (id: string, overrides: Partial<Media> = {}): Media => ({
  id,
  kind: 'image',
  url: `/api/media/${id}`,
  alt: `Picture ${id}`,
  width: 800,
  height: 600,
  annotations: [],
  ...overrides,
})

const video = (id: string, overrides: Partial<Media> = {}): Media => ({
  id,
  kind: 'video',
  url: `/api/media/${id}`,
  alt: '',
  width: null,
  height: null,
  annotations: [],
  ...overrides,
})

function guideWith(media: Media[], overrides: Partial<Guide> = {}): Guide {
  return guideFixture({
    status: 'published',
    publishedAt: '2026-07-01T09:00:00Z',
    version: 1,
    steps: [
      {
        id: 's1',
        orderIndex: 0,
        title: 'Mount the dish',
        bullets: [
          { id: 'b1', text: 'Slide the insert into place.', color: 'orange', icon: null, level: 0 },
          { id: 'b2', text: 'Check the clamp.', color: 'green', icon: null, level: 1 },
        ],
        media,
      },
    ],
    ...overrides,
  })
}

function picker(): HTMLInputElement {
  return document.querySelector('.media-slots input[type="file"]') as HTMLInputElement
}

function choose(...files: File[]) {
  fireEvent.change(picker(), { target: { files } })
}

/** A file of a given size without allocating it: only `size` is ever read. */
function fileOfSize(name: string, type: string, size: number): File {
  const file = new File(['x'], name, { type })
  Object.defineProperty(file, 'size', { value: size })
  return file
}

const PNG = () => new File(['png'], 'key.png', { type: 'image/png' })
const WEBM = () => new File(['webm'], 'insert.webm', { type: 'video/webm' })

describe('step media in the reader', () => {
  it('plays a video with native controls, loading only its metadata up front', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [guideWith([video('v1', { alt: 'Sliding the insert into place' })])],
    })
    renderApp({ route: '/g/confocal-startup', server })

    const player = (await screen.findByLabelText('Sliding the insert into place')) as HTMLVideoElement
    expect(player.tagName).toBe('VIDEO')
    expect(player).toHaveAttribute('src', '/api/media/v1')
    expect(player.controls).toBe(true)
    expect(player).toHaveAttribute('preload', 'metadata')
    expect(player.playsInline).toBe(true)
    /* Nothing treats it as a picture. */
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('names an undescribed video rather than leaving it anonymous', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [guideWith([video('v1')])] })
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByLabelText('Video for this step')).toBeInTheDocument()
  })

  it.each([
    [1, [image('a')]],
    [2, [image('a'), video('v')]],
    [3, [image('a'), video('v'), image('b')]],
  ])('lays out a step with %i media, in the order they were added', async (count, media) => {
    const server = createFakeServer({ user: VIEWER, guides: [guideWith(media)] })
    renderApp({ route: '/g/confocal-startup', server })

    await screen.findByRole('heading', { name: /Step 1: Mount the dish/ })
    const strip = document.querySelector('.step__media') as HTMLElement
    expect(strip).toHaveClass(`step__media--${count}`)
    expect(Array.from(strip.children).map((child) => (child.querySelector('video') ? 'video' : 'image'))).toEqual(
      media.map((item) => item.kind),
    )
  })

  it('never draws annotations over a video, even if some were stored with it', async () => {
    const stray = { id: 'a1', shape: 'rectangle', color: 'red', x: 0.1, y: 0.1, width: 0.2, height: 0.2 } as const
    const server = createFakeServer({
      user: VIEWER,
      guides: [guideWith([video('v1', { annotations: [stray] })])],
    })
    renderApp({ route: '/g/confocal-startup', server })

    await screen.findByLabelText('Video for this step')
    expect(document.querySelector('.annotated__overlay')).not.toBeInTheDocument()
  })

  it('gives the browser each picture\'s size, so the page does not jump as they load', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [guideWith([image('a', { width: 1280, height: 800 })])],
    })
    renderApp({ route: '/g/confocal-startup', server })

    const picture = await screen.findByRole('img', { name: 'Picture a' })
    expect(picture).toHaveAttribute('width', '1280')
    expect(picture).toHaveAttribute('height', '800')
  })
})

describe('the reader\'s actions', () => {
  it('links to the PDF as a plain download', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [guideWith([])] })
    renderApp({ route: '/g/confocal-startup', server })

    const pdf = await screen.findByRole('link', { name: 'PDF' })
    expect(pdf).toHaveAttribute('href', '/api/guides/confocal-startup/pdf')
    expect(pdf).toHaveAttribute('download')
    /* A link the browser follows, not a request the app makes. */
    expect(server.requests.some((request) => request.path.endsWith('/pdf'))).toBe(false)
  })

  it('tells an author in words that a draft is not what readers see', async () => {
    const server = createFakeServer({ guides: [guideFixture()] })
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByText('This guide is a draft.')).toBeInTheDocument()
  })

  it('shows tags by their display names', async () => {
    const server = createFakeServer({
      user: VIEWER,
      guides: [guideWith([], { tags: ['las-x'] })],
      tagNames: { 'las-x': 'LAS X' },
    })
    renderApp({ route: '/g/confocal-startup', server })

    expect(await screen.findByRole('link', { name: 'LAS X' })).toHaveAttribute('href', '/t/las-x')
  })
})

describe('step media in the editor', () => {
  it('takes a video into a slot, without an annotation tool', async () => {
    const server = createFakeServer()
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(WEBM())

    expect(await screen.findByRole('button', { name: 'Remove video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Describe video' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Annotate image' })).not.toBeInTheDocument()
    await waitFor(
      () => expect(server.state.guides[0].steps[0].media[0]).toMatchObject({ kind: 'video' }),
      { timeout: 4000 },
    )
  })

  it('takes a picture and a video together, in the order they were chosen', async () => {
    const server = createFakeServer()
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(PNG(), WEBM())

    await screen.findByRole('button', { name: 'Remove video' })
    await waitFor(
      () =>
        expect(server.state.guides[0].steps[0].media.map((item) => item.kind)).toEqual([
          'image',
          'video',
        ]),
      { timeout: 4000 },
    )
  })

  it('lets the author describe a video', async () => {
    const server = createFakeServer({ guides: [guideWith([video('v1')], { status: 'draft' })] })
    const user = userEvent.setup()
    renderApp({ route: '/g/g-confocal/edit', server })

    await user.click(await screen.findByRole('button', { name: 'Describe video' }))
    const dialog = screen.getByRole('dialog', { name: 'Step video' })
    await user.type(within(dialog).getByLabelText('Description'), 'Sliding the insert')
    await user.click(within(dialog).getByRole('button', { name: 'Done' }))

    await waitFor(
      () => expect(server.state.guides[0].steps[0].media[0].alt).toBe('Sliding the insert'),
      { timeout: 4000 },
    )
  })

  it('refuses a file of the wrong kind in words, without sending it', async () => {
    const server = createFakeServer()
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(new File(['x'], 'recording.avi', { type: 'video/x-msvideo' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '“recording.avi” is not a picture or a video Reticle can show',
    )
    expect(server.count('POST', '/media')).toBe(0)
  })

  it('refuses a video over the limit before uploading 200 MB of it', async () => {
    const server = createFakeServer()
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(fileOfSize('overnight.mp4', 'video/mp4', MAX_VIDEO_BYTES + 1))

    expect(await screen.findByRole('alert')).toHaveTextContent('a video can be at most 200 MB')
    expect(server.count('POST', '/media')).toBe(0)
  })

  it('uploads what fits and says what was left out when too many are dropped', async () => {
    const server = createFakeServer({
      guides: [guideWith([image('a'), image('b')], { status: 'draft' })],
    })
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Mount the dish')

    choose(PNG(), new File(['png'], 'fourth.png', { type: 'image/png' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A step holds 3 images or videos, so “fourth.png” was left out.',
    )
    await waitFor(() => expect(screen.getAllByRole('button', { name: 'Remove image' })).toHaveLength(3))
    expect(server.count('POST', '/media')).toBe(1)
    /* A full step offers nowhere to add a fourth. */
    expect(screen.queryByRole('button', { name: 'Add an image or video' })).not.toBeInTheDocument()
  })

  it('shows the server\'s own sentence when it refuses an upload', async () => {
    const server = createFakeServer()
    server.refuseNextUpload('payload_too_large', 'Videos must be at most 200 MB.', 413)
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(WEBM())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '“insert.webm” was not uploaded: Videos must be at most 200 MB.',
    )
    expect(screen.queryByRole('button', { name: 'Remove video' })).not.toBeInTheDocument()
    /* The slot is free again, and the message can be put away. */
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add an image or video' })).toBeInTheDocument()
  })

  it('keeps the files that went up when one of a batch is refused', async () => {
    const server = createFakeServer()
    renderApp({ route: '/g/g-confocal/edit', server })
    await screen.findByDisplayValue('Switch on the lasers')

    choose(PNG())
    await screen.findByRole('button', { name: 'Remove image' })
    server.refuseNextUpload('validation_failed', 'That file is not a readable image.', 422)
    choose(new File(['x'], 'broken.png', { type: 'image/png' }), WEBM())

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '“broken.png” was not uploaded: That file is not a readable image.',
    )
    expect(await screen.findByRole('button', { name: 'Remove video' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Remove image' })).toBeInTheDocument()
  })

  describe('with an upload that reports progress', () => {
    /** An upload held open by the test, which then feeds it progress and an ending. */
    function heldUpload() {
      let report: ((progress: UploadProgress) => void) | undefined
      let finish: ((response: Response) => void) | undefined
      let aborted = false

      const uploadImpl: UploadTransport = (_url, { onProgress, signal }) =>
        new Promise<Response>((resolve, reject) => {
          report = onProgress
          finish = resolve
          signal?.addEventListener('abort', () => {
            aborted = true
            reject(new DOMException('aborted', 'AbortError'))
          })
        })

      return {
        uploadImpl,
        progress: (loaded: number, total: number) => report?.({ loaded, total }),
        succeed: (media: Media) =>
          finish?.(new Response(JSON.stringify(media), { status: 201 })),
        get aborted() {
          return aborted
        },
      }
    }

    it('shows how far a large upload has got, then the video', async () => {
      const server = createFakeServer()
      const held = heldUpload()
      renderApp({ route: '/g/g-confocal/edit', server, uploadImpl: held.uploadImpl })
      await screen.findByDisplayValue('Switch on the lasers')

      choose(WEBM())

      const bar = await screen.findByRole('progressbar', { name: 'Upload progress' })
      await waitFor(() => expect(bar).toHaveAttribute('value', '0'))

      held.progress(42, 100)
      await waitFor(() => expect(bar).toHaveAttribute('value', '42'))
      expect(screen.getByText('42%')).toBeInTheDocument()
      /* The slot is spoken for while the upload runs. */
      expect(screen.queryByRole('button', { name: 'Add an image or video' })).not.toBeInTheDocument()

      held.succeed(video('m-up'))

      expect(await screen.findByRole('button', { name: 'Remove video' })).toBeInTheDocument()
      expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    })

    it('stops an upload on Cancel and treats that as a choice, not an error', async () => {
      const server = createFakeServer()
      const held = heldUpload()
      const user = userEvent.setup()
      renderApp({ route: '/g/g-confocal/edit', server, uploadImpl: held.uploadImpl })
      await screen.findByDisplayValue('Switch on the lasers')

      choose(WEBM())
      await user.click(await screen.findByRole('button', { name: 'Cancel' }))

      await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())
      expect(held.aborted).toBe(true)
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Add an image or video' })).toBeInTheDocument()
    })
  })
})

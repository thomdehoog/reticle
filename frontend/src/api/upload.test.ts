import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError, xhrUpload, type UploadTransport } from './client'

/**
 * A stand-in for the browser's XMLHttpRequest, driven by hand.
 *
 * jsdom ships a real one that would try to open a socket. What matters here is
 * the contract `xhrUpload` relies on — headers set before send, progress on
 * `upload`, the three ways a request can end — so that is all this models.
 */
class FakeXhr {
  static last: FakeXhr
  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: unknown = null
  status = 0
  responseText = ''
  responseType = 'application/json'
  aborted = false
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  ontimeout: (() => void) | null = null
  onabort: (() => void) | null = null

  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value
  }
  getResponseHeader(name: string) {
    return name === 'Content-Type' ? this.responseType : null
  }
  send(body: unknown) {
    this.body = body
  }
  abort() {
    this.aborted = true
    this.onabort?.()
  }

  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
  }
  respond(status: number, body: string, type = 'application/json') {
    this.status = status
    this.responseText = body
    this.responseType = type
    this.onload?.()
  }
}

function useFakeXhr() {
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
}

const FILE = new File(['frames'], 'insert.webm', { type: 'video/webm' })

afterEach(() => vi.unstubAllGlobals())

describe('uploading through the API client', () => {
  it('sends the file as multipart with the CSRF token, and reports progress', async () => {
    useFakeXhr()
    const client = new ApiClient({ readCsrfToken: () => 'csrf-abc' })
    const onProgress = vi.fn()

    const pending = client.upload<{ id: string }>('/media', FILE, { onProgress })
    const xhr = FakeXhr.last

    expect(xhr.method).toBe('POST')
    expect(xhr.url).toBe('/api/media')
    expect(xhr.headers['X-CSRF-Token']).toBe('csrf-abc')
    /* The browser writes the multipart boundary; setting the type would break it. */
    expect(xhr.headers['Content-Type']).toBeUndefined()
    expect((xhr.body as FormData).get('file')).toBeInstanceOf(File)

    xhr.progress(50, 200)
    xhr.progress(200, 200)
    expect(onProgress.mock.calls).toEqual([[{ loaded: 50, total: 200 }], [{ loaded: 200, total: 200 }]])

    xhr.respond(201, JSON.stringify({ id: 'm1' }))
    await expect(pending).resolves.toEqual({ id: 'm1' })
  })

  it('maps a refused upload to the same typed error as any other request', async () => {
    useFakeXhr()
    const pending = new ApiClient().upload('/media', FILE)
    FakeXhr.last.respond(
      413,
      JSON.stringify({ error: { code: 'payload_too_large', message: 'Videos must be at most 200 MB.' } }),
    )

    await expect(pending).rejects.toMatchObject({
      code: 'payload_too_large',
      message: 'Videos must be at most 200 MB.',
      status: 413,
    })
  })

  it('understands a body-size refusal from the proxy, which is not JSON', async () => {
    useFakeXhr()
    const pending = new ApiClient().upload('/media', FILE)
    FakeXhr.last.respond(413, '<html><h1>413 Request Entity Too Large</h1></html>', 'text/html')

    await expect(pending).rejects.toMatchObject({
      code: 'payload_too_large',
      message: 'That file is larger than the server accepts.',
    })
  })

  it('drops to the login screen when the session ended during an upload', async () => {
    useFakeXhr()
    const onUnauthenticated = vi.fn()
    const pending = new ApiClient({ onUnauthenticated }).upload('/media', FILE)
    FakeXhr.last.respond(
      401,
      JSON.stringify({ error: { code: 'not_authenticated', message: 'Not signed in.' } }),
    )

    await expect(pending).rejects.toBeInstanceOf(ApiError)
    expect(onUnauthenticated).toHaveBeenCalledTimes(1)
  })

  it('reports a dropped connection as a network error', async () => {
    useFakeXhr()
    const pending = new ApiClient().upload('/media', FILE)
    FakeXhr.last.onerror?.()

    await expect(pending).rejects.toMatchObject({ code: 'network_error', status: 0 })
  })

  it('stops the request when the caller aborts, and says it was cancelled', async () => {
    useFakeXhr()
    const controller = new AbortController()
    const pending = new ApiClient().upload('/media', FILE, { signal: controller.signal })

    controller.abort()

    expect(FakeXhr.last.aborted).toBe(true)
    await expect(pending).rejects.toMatchObject({ code: 'cancelled' })
  })

  it('never opens a request for a signal that is already aborted', async () => {
    useFakeXhr()
    const controller = new AbortController()
    controller.abort()

    await expect(
      xhrUpload('/api/media', { headers: {}, body: new FormData(), signal: controller.signal }),
    ).rejects.toMatchObject({ name: 'AbortError' })
    expect(FakeXhr.last.body).toBeNull()
  })

  it('handles a response that has no body', async () => {
    useFakeXhr()
    const pending = new ApiClient().upload('/media', FILE)
    FakeXhr.last.respond(204, '')

    await expect(pending).resolves.toBeUndefined()
  })

  it('uploads through an injected fetch when that is all it was given', async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ id: 'm1' }), { status: 201 }),
    ) as unknown as typeof fetch

    await expect(new ApiClient({ fetchImpl }).upload('/media', FILE)).resolves.toEqual({ id: 'm1' })
    const [url, init] = (fetchImpl as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/media')
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('prefers an injected upload transport over both', async () => {
    const uploadImpl: UploadTransport = vi.fn(async (_url, { onProgress }) => {
      onProgress?.({ loaded: 1, total: 2 })
      return new Response(JSON.stringify({ id: 'm9' }), { status: 201 })
    })
    const onProgress = vi.fn()

    await expect(
      new ApiClient({ uploadImpl }).upload('/media', FILE, { onProgress }),
    ).resolves.toEqual({ id: 'm9' })
    expect(onProgress).toHaveBeenCalledWith({ loaded: 1, total: 2 })
  })
})

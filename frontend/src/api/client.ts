/**
 * The single HTTP transport for Reticle.
 *
 * There is deliberately no second "offline" or "mock" implementation of the
 * API: two implementations of one contract drift apart and double the
 * maintenance. Tests inject a fake `fetch` here instead, so the code under test
 * is always the code that ships.
 */

/** Server error codes from docs/API.md. Callers switch on these, never on prose. */
export type ApiErrorCode =
  | 'invalid_credentials'
  | 'not_authenticated'
  | 'forbidden'
  | 'not_found'
  | 'validation_failed'
  | 'conflict'
  | 'rate_limited'
  | 'payload_too_large'
  | 'network_error'
  | 'cancelled'
  | 'unexpected'

export class ApiError extends Error {
  readonly code: ApiErrorCode
  readonly status: number

  constructor(code: ApiErrorCode, message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }

  /** True when retrying the identical request could plausibly succeed. */
  get isTransient(): boolean {
    return this.code === 'network_error' || this.status >= 500
  }
}

export interface UploadProgress {
  loaded: number
  total: number
}

export interface UploadOptions {
  /** Called as bytes leave the browser; a 200 MB video takes long enough to need it. */
  onProgress?: (progress: UploadProgress) => void
  /** Aborting it stops the upload; the request then fails with `cancelled`. */
  signal?: AbortSignal
}

/**
 * How a multipart body is put on the wire. It answers with an ordinary
 * `Response`, so an upload is parsed, and its errors mapped, by exactly the
 * code that handles every other request.
 */
export type UploadTransport = (
  url: string,
  init: { headers: Record<string, string>; body: FormData } & UploadOptions,
) => Promise<Response>

/**
 * Uploads through `XMLHttpRequest`, the one browser API that reports how much
 * of a request body has been sent — `fetch` still cannot. This is a different
 * socket call, not a second data path: it is reached only through
 * `ApiClient.upload`, with the same headers going in and the same response
 * handling coming out.
 */
export const xhrUpload: UploadTransport = (url, { headers, body, onProgress, signal }) =>
  new Promise<Response>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)
    for (const [name, value] of Object.entries(headers)) xhr.setRequestHeader(name, value)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.({ loaded: event.loaded, total: event.total })
    }
    xhr.onload = () => {
      const type = xhr.getResponseHeader('Content-Type')
      /* A response that may not have a body must not be given one, even an
         empty string — the constructor refuses. */
      const bodiless = xhr.status === 204 || xhr.status === 205 || xhr.status === 304
      resolve(
        new Response(bodiless ? null : xhr.responseText, {
          status: xhr.status,
          headers: type ? { 'Content-Type': type } : undefined,
        }),
      )
    }
    xhr.onerror = () => reject(new TypeError('The upload could not reach the server.'))
    xhr.ontimeout = xhr.onerror
    xhr.onabort = () => reject(new DOMException('The upload was cancelled.', 'AbortError'))

    if (signal?.aborted) {
      reject(new DOMException('The upload was cancelled.', 'AbortError'))
      return
    }
    signal?.addEventListener('abort', () => xhr.abort(), { once: true })

    xhr.send(body)
  })

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === 'AbortError'
}

export interface ApiClientOptions {
  baseUrl?: string
  fetchImpl?: typeof fetch
  /**
   * Replaces the upload transport. When only `fetchImpl` is replaced — a test
   * around an in-memory server — uploads go through that instead, so they
   * reach the same fake; there is no socket there for progress to measure.
   */
  uploadImpl?: UploadTransport
  /** Reads the CSRF cookie; injectable because jsdom has no real cookie jar. */
  readCsrfToken?: () => string | null
  /**
   * Called when the server reports the session is gone, so the app can drop to
   * the login screen from anywhere, including a background autosave. Only
   * `not_authenticated` triggers it; a rejected login is `invalid_credentials`
   * and stays on the form as a field error.
   */
  onUnauthenticated?: () => void
}

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function readCsrfCookieFromDocument(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)reticle_csrf=([^;]*)/)
  return match ? decodeURIComponent(match[1]) : null
}

export class ApiClient {
  private readonly baseUrl: string
  private readonly fetchImpl: typeof fetch
  private readonly uploadImpl: UploadTransport
  private readonly readCsrfToken: () => string | null
  private readonly onUnauthenticated?: () => void

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '/api'
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
    const injected = options.fetchImpl
    this.uploadImpl =
      options.uploadImpl ??
      (injected
        ? (url, { headers, body, signal }) =>
            injected(url, { method: 'POST', headers, credentials: 'same-origin', body, signal })
        : xhrUpload)
    this.readCsrfToken = options.readCsrfToken ?? readCsrfCookieFromDocument
    this.onUnauthenticated = options.onUnauthenticated
  }

  /**
   * The address of a resource the browser fetches by itself — a download link
   * or an image source — where there is no request for this client to send.
   */
  url(path: string): string {
    return `${this.baseUrl}${path}`
  }

  get<T>(path: string): Promise<T> {
    return this.send<T>('GET', path)
  }

  post<T>(path: string, body?: unknown): Promise<T> {
    return this.send<T>('POST', path, body)
  }

  put<T>(path: string, body: unknown): Promise<T> {
    return this.send<T>('PUT', path, body)
  }

  patch<T>(path: string, body: unknown): Promise<T> {
    return this.send<T>('PATCH', path, body)
  }

  delete<T>(path: string): Promise<T> {
    return this.send<T>('DELETE', path)
  }

  /**
   * Uploads one file — an image or a video. The browser sets the multipart
   * boundary, so we must not.
   */
  upload<T>(path: string, file: File, options: UploadOptions = {}): Promise<T> {
    const form = new FormData()
    form.append('file', file)
    return this.settle<T>(() =>
      this.uploadImpl(`${this.baseUrl}${path}`, {
        headers: this.headersFor('POST', form),
        body: form,
        ...options,
      }),
    )
  }

  private send<T>(method: string, path: string, body?: unknown): Promise<T> {
    return this.settle<T>(() =>
      this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers: this.headersFor(method, body),
        credentials: 'same-origin',
        body:
          body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
      }),
    )
  }

  private headersFor(method: string, body: unknown): Record<string, string> {
    const headers: Record<string, string> = {}
    if (body !== undefined && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json'
    }
    if (MUTATING_METHODS.has(method)) {
      const token = this.readCsrfToken()
      if (token) headers['X-CSRF-Token'] = token
    }
    return headers
  }

  /** Everything that happens to a response, whichever transport produced it. */
  private async settle<T>(request: () => Promise<Response>): Promise<T> {
    let response: Response
    try {
      response = await request()
    } catch (cause) {
      if (isAbort(cause)) throw new ApiError('cancelled', 'The upload was cancelled.', 0)
      throw new ApiError(
        'network_error',
        'Could not reach the Reticle server. Check your connection and try again.',
        0,
      )
    }

    if (response.ok) return this.parseBody<T>(response)

    const error = await this.parseError(response)
    if (error.code === 'not_authenticated') this.onUnauthenticated?.()
    throw error
  }

  private async parseBody<T>(response: Response): Promise<T> {
    if (response.status === 204) return undefined as T

    const text = await response.text()
    if (text === '') return undefined as T

    try {
      return JSON.parse(text) as T
    } catch {
      throw new ApiError('unexpected', 'The server returned a malformed response.', response.status)
    }
  }

  private async parseError(response: Response): Promise<ApiError> {
    let code: ApiErrorCode = 'unexpected'
    let message = `The server returned an unexpected error (${response.status}).`

    try {
      const payload = (await response.json()) as { error?: { code?: string; message?: string } }
      if (payload.error?.code) code = payload.error.code as ApiErrorCode
      if (payload.error?.message) message = payload.error.message
    } catch {
      if (response.status === 401) code = 'not_authenticated'
      if (response.status === 403) code = 'forbidden'
      if (response.status === 404) code = 'not_found'
      /* The proxy in front of the server has its own body limit and answers
         in HTML, not in the API's JSON. */
      if (response.status === 413) {
        code = 'payload_too_large'
        message = 'That file is larger than the server accepts.'
      }
    }

    return new ApiError(code, message, response.status)
  }
}

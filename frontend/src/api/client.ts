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

export interface ApiClientOptions {
  baseUrl?: string
  fetchImpl?: typeof fetch
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
  private readonly readCsrfToken: () => string | null
  private readonly onUnauthenticated?: () => void

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = options.baseUrl ?? '/api'
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
    this.readCsrfToken = options.readCsrfToken ?? readCsrfCookieFromDocument
    this.onUnauthenticated = options.onUnauthenticated
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

  /* A body is unusual on DELETE and is what carries the password confirming a
     section's removal. Optional, because everything else deleted here needs no
     second word. */
  delete<T>(path: string, body?: unknown): Promise<T> {
    return this.send<T>('DELETE', path, body)
  }

  /** Uploads one image. The browser sets the multipart boundary, so we must not. */
  upload<T>(path: string, file: File): Promise<T> {
    const form = new FormData()
    form.append('file', file)
    return this.send<T>('POST', path, form)
  }

  private async send<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {}
    const isForm = body instanceof FormData

    if (body !== undefined && !isForm) headers['Content-Type'] = 'application/json'

    if (MUTATING_METHODS.has(method)) {
      const token = this.readCsrfToken()
      if (token) headers['X-CSRF-Token'] = token
    }

    let response: Response
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        credentials: 'same-origin',
        body: isForm ? (body as FormData) : body === undefined ? undefined : JSON.stringify(body),
      })
    } catch {
      // The binding is dropped on purpose. fetch rejects with a bare TypeError
      // whose message varies by browser and says nothing a user could act on;
      // the sentence below is the whole of what is worth telling them.
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
    }

    return new ApiError(code, message, response.status)
  }
}

import { describe, expect, it, vi } from 'vitest'

import { ApiClient, ApiError } from './client'

interface RecordedCall {
  url: string
  init: RequestInit
}

function fakeTransport(responder: (call: RecordedCall) => Response | Promise<Response>) {
  const calls: RecordedCall[] = []
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const call = { url: String(url), init: init ?? {} }
    calls.push(call)
    return responder(call)
  }) as unknown as typeof fetch
  return { fetchImpl, calls }
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function errorResponse(code: string, message: string, status: number): Response {
  return jsonResponse({ error: { code, message } }, status)
}

function headersOf(call: RecordedCall): Record<string, string> {
  return (call.init.headers ?? {}) as Record<string, string>
}

describe('ApiClient', () => {
  it('prefixes the base path and parses a JSON body', async () => {
    const { fetchImpl, calls } = fakeTransport(() => jsonResponse({ id: 'g1', title: 'Confocal' }))
    const client = new ApiClient({ fetchImpl })

    await expect(client.get('/guides/g1')).resolves.toEqual({ id: 'g1', title: 'Confocal' })
    expect(calls[0].url).toBe('/api/guides/g1')
    expect(calls[0].init.method).toBe('GET')
  })

  it('sends the session cookie with every request', async () => {
    const { fetchImpl, calls } = fakeTransport(() => jsonResponse({}))
    await new ApiClient({ fetchImpl }).get('/auth/me')
    expect(calls[0].init.credentials).toBe('same-origin')
  })

  it('attaches the CSRF token to mutating requests only', async () => {
    const { fetchImpl, calls } = fakeTransport(() => jsonResponse({}))
    const client = new ApiClient({ fetchImpl, readCsrfToken: () => 'csrf-abc' })

    await client.get('/guides')
    await client.post('/guides', { title: 'x' })
    await client.delete('/guides/g1')

    expect(headersOf(calls[0])['X-CSRF-Token']).toBeUndefined()
    expect(headersOf(calls[1])['X-CSRF-Token']).toBe('csrf-abc')
    expect(headersOf(calls[2])['X-CSRF-Token']).toBe('csrf-abc')
  })

  it('serialises JSON bodies but leaves multipart uploads to the browser', async () => {
    const { fetchImpl, calls } = fakeTransport(() => jsonResponse({ id: 'm1' }))
    const client = new ApiClient({ fetchImpl })

    await client.post('/guides', { title: 'Confocal' })
    await client.upload('/media', new File(['bytes'], 'shot.png', { type: 'image/png' }))

    expect(headersOf(calls[0])['Content-Type']).toBe('application/json')
    expect(calls[0].init.body).toBe('{"title":"Confocal"}')
    expect(headersOf(calls[1])['Content-Type']).toBeUndefined()
    expect(calls[1].init.body).toBeInstanceOf(FormData)
  })

  it('maps a server error payload onto ApiError', async () => {
    const { fetchImpl } = fakeTransport(() =>
      errorResponse('conflict', 'Someone else saved this guide first.', 409),
    )
    const client = new ApiClient({ fetchImpl })

    const error = await client.put('/guides/g1', {}).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('conflict')
    expect((error as ApiError).status).toBe(409)
    expect((error as ApiError).message).toBe('Someone else saved this guide first.')
  })

  it('signals a lost session so the app can return to the login screen', async () => {
    const onUnauthenticated = vi.fn()
    const { fetchImpl } = fakeTransport(() =>
      errorResponse('not_authenticated', 'Your session has expired.', 401),
    )
    const client = new ApiClient({ fetchImpl, onUnauthenticated })

    await client.get('/guides').catch(() => undefined)
    expect(onUnauthenticated).toHaveBeenCalledOnce()
  })

  it('does not bounce to login when the credentials themselves were wrong', async () => {
    const onUnauthenticated = vi.fn()
    const { fetchImpl } = fakeTransport(() =>
      errorResponse('invalid_credentials', 'Email or password is incorrect.', 401),
    )
    const client = new ApiClient({ fetchImpl, onUnauthenticated })

    const error = await client.post('/auth/login', {}).catch((e: unknown) => e)
    expect((error as ApiError).code).toBe('invalid_credentials')
    expect(onUnauthenticated).not.toHaveBeenCalled()
  })

  it('reports an unreachable server as a transient network error', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch
    const client = new ApiClient({ fetchImpl })

    const error = (await client.get('/guides').catch((e: unknown) => e)) as ApiError
    expect(error.code).toBe('network_error')
    expect(error.isTransient).toBe(true)
    expect(error.message).toContain('Could not reach the Reticle server')
  })

  it('treats a 204 as an empty result rather than a parse failure', async () => {
    const { fetchImpl } = fakeTransport(() => new Response(null, { status: 204 }))
    await expect(new ApiClient({ fetchImpl }).delete('/guides/g1')).resolves.toBeUndefined()
  })

  it('falls back to the status code when the error body is not JSON', async () => {
    const { fetchImpl } = fakeTransport(() => new Response('<html>502</html>', { status: 403 }))
    const error = (await new ApiClient({ fetchImpl }).get('/users').catch((e: unknown) => e)) as ApiError
    expect(error.code).toBe('forbidden')
    expect(error.status).toBe(403)
  })

  it('downloads a file as a blob, through the same request and error handling', async () => {
    const { fetchImpl, calls } = fakeTransport(
      () => new Response('%PDF-1.4', { headers: { 'Content-Type': 'application/pdf' } }),
    )

    const blob = await new ApiClient({ fetchImpl }).download('/guides/g1/pdf?view=published')

    expect(await blob.text()).toBe('%PDF-1.4')
    expect(calls[0].url).toBe('/api/guides/g1/pdf?view=published')
    expect(calls[0].init).toMatchObject({ method: 'GET', credentials: 'same-origin' })
  })

  it('turns a refused download into an error, so it is never saved as the file', async () => {
    const onUnauthenticated = vi.fn()
    const { fetchImpl } = fakeTransport(() => errorResponse('not_authenticated', 'Sign in.', 401))
    const client = new ApiClient({ fetchImpl, onUnauthenticated })

    const error = (await client.download('/guides/g1/pdf').catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('not_authenticated')
    expect(onUnauthenticated).toHaveBeenCalledTimes(1)
  })

  it('reads how long a busy server asked it to wait', async () => {
    const busy = (retryAfter?: string) => () =>
      new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'Busy.' } }), {
        status: 429,
        headers: {
          'Content-Type': 'application/json',
          ...(retryAfter === undefined ? {} : { 'Retry-After': retryAfter }),
        },
      })
    const failure = async (retryAfter?: string) =>
      (await new ApiClient({ fetchImpl: fakeTransport(busy(retryAfter)).fetchImpl })
        .download('/guides/g1/pdf')
        .catch((e: unknown) => e)) as ApiError

    expect((await failure('5')).retryAfterSeconds).toBe(5)
    expect((await failure(' 12 ')).retryAfterSeconds).toBe(12)
    expect((await failure('0')).retryAfterSeconds).toBe(0)
    expect((await failure()).retryAfterSeconds).toBeNull()
    /* The date form, and nonsense, are "the server did not say". */
    expect((await failure('Wed, 21 Oct 2026 07:28:00 GMT')).retryAfterSeconds).toBeNull()
    expect((await failure('-3')).retryAfterSeconds).toBeNull()
    expect((await failure('5')).code).toBe('rate_limited')
  })

  it('has no waiting time on an ordinary error', () => {
    expect(new ApiError('not_found', 'Not found.', 404).retryAfterSeconds).toBeNull()
  })
})

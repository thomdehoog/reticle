import { describe, expect, it, vi } from 'vitest'

import { ApiError } from './client'
import { createQueryClient, shouldRetry } from './queryClient'

describe('shouldRetry', () => {
  it.each([
    ['not_found', 404],
    ['forbidden', 403],
    ['not_authenticated', 401],
    ['validation_failed', 422],
    ['conflict', 409],
    ['rate_limited', 429],
  ] as const)('never retries %s — the server meant it', (code, status) => {
    expect(shouldRetry(0, new ApiError(code, 'no', status))).toBe(false)
  })

  it('retries a server fault or a dropped connection, but not for ever', () => {
    const fault = new ApiError('unexpected', 'boom', 503)
    const offline = new ApiError('network_error', 'offline', 0)

    expect(shouldRetry(0, fault)).toBe(true)
    expect(shouldRetry(1, offline)).toBe(true)
    expect(shouldRetry(2, fault)).toBe(false)
  })

  it('does not retry something that is not an API error at all', () => {
    expect(shouldRetry(0, new TypeError('a bug'))).toBe(false)
  })
})

describe('createQueryClient', () => {
  it('asks once for a 404 and reports it', async () => {
    const queryFn = vi.fn().mockRejectedValue(new ApiError('not_found', 'No such guide.', 404))
    const client = createQueryClient()

    await expect(client.fetchQuery({ queryKey: ['guide'], queryFn })).rejects.toMatchObject({
      code: 'not_found',
    })
    expect(queryFn).toHaveBeenCalledTimes(1)
  })

  it('does not retry at all when told not to, as in tests', async () => {
    const queryFn = vi.fn().mockRejectedValue(new ApiError('unexpected', 'boom', 500))
    const client = createQueryClient({ retry: false })

    await expect(client.fetchQuery({ queryKey: ['guide'], queryFn })).rejects.toBeInstanceOf(ApiError)
    expect(queryFn).toHaveBeenCalledTimes(1)
  })

  it('serves a read from cache while it is fresh, and never retries a mutation', async () => {
    const client = createQueryClient()
    const queryFn = vi.fn().mockResolvedValue(['a'])

    await client.fetchQuery({ queryKey: ['list'], queryFn })
    await client.fetchQuery({ queryKey: ['list'], queryFn })

    expect(queryFn).toHaveBeenCalledTimes(1)
    expect(client.getDefaultOptions().mutations?.retry).toBe(false)
  })
})

import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from './client'
import { ReticleApi } from './reticle'

/** Records what the façade asks for, and answers every request with `reply`. */
function recordingApi(reply: () => Response = () => new Response(null, { status: 204 })) {
  const calls: { method: string; url: string; body: unknown }[] = []
  const fetchImpl = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({
      method: init?.method ?? 'GET',
      url: String(url),
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    })
    return reply()
  }) as unknown as typeof fetch
  return { api: new ReticleApi(new ApiClient({ fetchImpl, readCsrfToken: () => 'csrf' })), calls }
}

const json = (body: unknown) => () =>
  new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })

describe('ReticleApi — the contract in docs/API.md', () => {
  it('records a read with a POST that carries no body', async () => {
    const { api, calls } = recordingApi()

    await expect(api.recordGuideView('g1')).resolves.toBeUndefined()
    await expect(api.recordPageView('p1')).resolves.toBeUndefined()

    expect(calls).toEqual([
      { method: 'POST', url: '/api/guides/g1/view', body: undefined },
      { method: 'POST', url: '/api/pages/p1/view', body: undefined },
    ])
  })

  it('builds the PDF address without asking the server anything', () => {
    const { api, calls } = recordingApi()

    expect(api.guidePdfUrl('confocal-startup')).toBe('/api/guides/confocal-startup/pdf')
    expect(api.guidePdfUrl('a slug/with?odd#bits')).toBe(
      '/api/guides/a%20slug%2Fwith%3Fodd%23bits/pdf',
    )
    expect(api.mediaUrl('m1')).toBe('/api/media/m1')
    expect(calls).toHaveLength(0)
  })

  it('archives a page with DELETE and reads one past revision of it', async () => {
    const { api, calls } = recordingApi()

    await api.archivePage('p1')
    await api.getPageRevision('p1', 3)

    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      'DELETE /api/pages/p1',
      'GET /api/pages/p1/revisions/3',
    ])
  })

  it('reads "no landing page" as null rather than as an error', async () => {
    const { api } = recordingApi(json(null))
    await expect(api.getCategoryLandingPage('c1')).resolves.toBeNull()
  })

  it('sends isHidden when creating and when updating a category', async () => {
    const { api, calls } = recordingApi(json({}))

    await api.createCategory({ name: 'Confocal - hidden guides', isHidden: true })
    await api.updateCategory('c1', { isHidden: false })

    expect(calls[0]).toMatchObject({
      method: 'POST',
      url: '/api/categories',
      body: { name: 'Confocal - hidden guides', isHidden: true },
    })
    expect(calls[1]).toMatchObject({
      method: 'PATCH',
      url: '/api/categories/c1',
      body: { isHidden: false },
    })
  })

  it('carries expectedUpdatedAt on every whole-document save', async () => {
    const { api, calls } = recordingApi(json({}))
    const stamp = '2026-07-01T08:00:00Z'

    await api.saveGuide({ id: 'g1', updatedAt: stamp } as never)
    await api.savePage({ id: 'p1', updatedAt: stamp } as never)

    expect(calls[0]).toMatchObject({ method: 'PUT', url: '/api/guides/g1' })
    expect(calls[0].body).toMatchObject({ expectedUpdatedAt: stamp })
    expect(calls[1]).toMatchObject({ method: 'PUT', url: '/api/pages/p1' })
    expect(calls[1].body).toMatchObject({ expectedUpdatedAt: stamp })
  })

  it('asks for guides by tag with the comma-separated form the server expects', async () => {
    const { api, calls } = recordingApi(json([]))

    await api.listGuides({ tags: 'stellaris,confocal', categoryId: '' })

    expect(calls[0].url).toBe('/api/guides?tags=stellaris%2Cconfocal')
  })
})

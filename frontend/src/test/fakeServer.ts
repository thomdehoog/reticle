/**
 * An in-memory stand-in for the Reticle backend, used only by tests.
 *
 * This is test scaffolding, not a second implementation of the app: components
 * under test still go through the real `ApiClient` and the real request/response
 * shapes, so a contract mistake surfaces here rather than in production.
 */

import type { Category, Guide, GuideSummary, Media, User } from '../domain/types'

export interface FakeServerState {
  user: User
  categories: Category[]
  guides: Guide[]
  media: Media[]
}

const ADMIN: User = {
  id: 'u-thom',
  email: 'thom.dehoog@zmb.uzh.ch',
  displayName: 'Thom de Hoog',
  role: 'admin',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

export function guideFixture(overrides: Partial<Guide> = {}): Guide {
  const author = { id: ADMIN.id, displayName: ADMIN.displayName }
  return {
    id: 'g-confocal',
    slug: 'confocal-startup',
    title: 'Confocal startup',
    summary: '',
    categoryId: 'c-light',
    tags: [],
    difficulty: 'moderate',
    timeRequiredMinMinutes: 30,
    timeRequiredMaxMinutes: null,
    introduction: '',
    conclusion: '',
    status: 'draft',
    steps: [
      {
        id: 's1',
        orderIndex: 0,
        title: 'Switch on the lasers',
        bullets: [{ id: 'b1', text: 'Turn the key.', color: 'black', icon: null, level: 0 }],
        media: [],
      },
    ],
    author,
    lastEditedBy: author,
    contributors: [author],
    viewCount: 0,
    createdAt: '2026-07-01T08:00:00Z',
    updatedAt: '2026-07-01T08:00:00Z',
    publishedAt: null,
    version: 0,
    ...overrides,
  }
}

export function createFakeServer(initial: Partial<FakeServerState> = {}) {
  const state: FakeServerState = {
    user: initial.user ?? ADMIN,
    categories: initial.categories ?? [
      {
        id: 'c-light',
        slug: 'light-microscopy',
        name: 'Light Microscopy',
        description: '',
        parentId: null,
        orderIndex: 2,
        isHidden: false,
      },
    ],
    guides: initial.guides ?? [guideFixture()],
    media: initial.media ?? [],
  }

  const requests: { method: string; path: string; body: unknown }[] = []
  let authenticated = true
  let saveCount = 0
  /** Set by a test to make the next save look like a colleague got there first. */
  let conflictOnNextSave = false

  function json(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  function error(code: string, message: string, status: number): Response {
    return json({ error: { code, message } }, status)
  }

  function summarise(guide: Guide): GuideSummary {
    return {
      id: guide.id,
      slug: guide.slug,
      title: guide.title,
      summary: guide.summary,
      categoryId: guide.categoryId,
      tags: guide.tags,
      difficulty: guide.difficulty,
      timeRequiredMinMinutes: guide.timeRequiredMinMinutes,
      timeRequiredMaxMinutes: guide.timeRequiredMaxMinutes,
      status: guide.status,
      stepCount: guide.steps.length,
      author: guide.author,
      viewCount: guide.viewCount,
      updatedAt: guide.updatedAt,
      publishedAt: guide.publishedAt,
    }
  }

  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), 'http://reticle.test')
    const path = url.pathname.replace(/^\/api/, '')
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body
    requests.push({ method, path, body })

    if (path === '/auth/login' && method === 'POST') {
      const credentials = body as { email: string; password: string }
      if (credentials.password !== 'correct-horse-battery') {
        return error('invalid_credentials', 'Email or password is incorrect.', 401)
      }
      authenticated = true
      return json(state.user)
    }

    if (path === '/auth/me') {
      return authenticated
        ? json(state.user)
        : error('not_authenticated', 'Not signed in.', 401)
    }

    if (!authenticated) return error('not_authenticated', 'Not signed in.', 401)

    if (path === '/categories' && method === 'GET') return json(state.categories)

    if (path === '/guides' && method === 'GET') return json(state.guides.map(summarise))

    const guideMatch = path.match(/^\/guides\/([^/]+)$/)
    if (guideMatch) {
      const key = decodeURIComponent(guideMatch[1])
      const guide = state.guides.find((g) => g.id === key || g.slug === key)
      if (!guide) return error('not_found', 'No such guide.', 404)

      if (method === 'GET') return json(guide)

      if (method === 'PUT') {
        if (conflictOnNextSave) {
          conflictOnNextSave = false
          return error('conflict', 'Someone else saved this guide first.', 409)
        }
        saveCount += 1
        const incoming = body as Guide
        const saved: Guide = {
          ...guide,
          ...incoming,
          steps: incoming.steps.map((step, index) => ({ ...step, orderIndex: index })),
          updatedAt: `2026-07-01T08:${String(saveCount).padStart(2, '0')}:00Z`,
        }
        state.guides = state.guides.map((g) => (g.id === guide.id ? saved : g))
        return json(saved)
      }
    }

    const publishMatch = path.match(/^\/guides\/([^/]+)\/publish$/)
    if (publishMatch && method === 'POST') {
      const guide = state.guides.find((g) => g.id === publishMatch[1])
      if (!guide) return error('not_found', 'No such guide.', 404)
      const published: Guide = {
        ...guide,
        status: 'published',
        version: guide.version + 1,
        publishedAt: '2026-07-01T09:00:00Z',
      }
      state.guides = state.guides.map((g) => (g.id === guide.id ? published : g))
      return json(published)
    }

    if (path === '/media' && method === 'POST') {
      const image: Media = {
        id: `m-${state.media.length + 1}`,
        url: `/api/media/m-${state.media.length + 1}`,
        alt: '',
        width: 800,
        height: 600,
        annotations: [],
      }
      state.media.push(image)
      return json(image)
    }

    return error('not_found', `Fake server has no route for ${method} ${path}`, 404)
  }) as unknown as typeof fetch

  return {
    fetchImpl,
    state,
    requests,
    get saveCount() {
      return saveCount
    },
    signOut() {
      authenticated = false
    },
    failNextSaveWithConflict() {
      conflictOnNextSave = true
    },
  }
}

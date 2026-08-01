/**
 * An in-memory stand-in for the Reticle backend, used only by tests.
 *
 * This is test scaffolding, not a second implementation of the app: components
 * under test still go through the real `ApiClient` and the real request/response
 * shapes, so a contract mistake surfaces here rather than in production.
 *
 * Where the real server applies a visibility or a validation rule that a screen
 * depends on — a hidden category, a 409 on deleting a category that still holds
 * guides, a landing page belonging to exactly one category — the rule is
 * reproduced here rather than stubbed away, because those are precisely the
 * paths the UI has to get right.
 */

import type { RevisionSummary } from '../api/reticle'
import type {
  Category,
  Guide,
  GuideSummary,
  Media,
  Page,
  PageSummary,
  SearchResult,
  Tag,
  User,
} from '../domain/types'

export interface FakeServerState {
  user: User
  users: User[]
  categories: Category[]
  guides: Guide[]
  pages: Page[]
  media: Media[]
  /** Published snapshots, newest last, keyed by guide or page id. */
  revisions: Record<string, { version: number; publishedAt: string; document: Guide | Page }[]>
}

const ADMIN: User = {
  id: 'u-thom',
  email: 'thom.dehoog@zmb.uzh.ch',
  displayName: 'Thom de Hoog',
  role: 'admin',
  isActive: true,
  createdAt: '2026-01-01T00:00:00Z',
}

export function imageFixture(overrides: Partial<Media> = {}): Media {
  return {
    id: 'm1',
    url: '/api/media/m1',
    kind: 'image',
    alt: '',
    width: 800,
    height: 600,
    durationSeconds: null,
    posterUrl: null,
    annotations: [],
    ...overrides,
  }
}

export function videoFixture(overrides: Partial<Media> = {}): Media {
  return {
    id: 'v1',
    url: '/api/media/v1',
    kind: 'video',
    alt: 'Seating the filter cube',
    width: 1280,
    height: 720,
    durationSeconds: 14,
    posterUrl: '/api/media/v1-poster',
    annotations: [],
    ...overrides,
  }
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
        video: null,
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

export function pageFixture(overrides: Partial<Page> = {}): Page {
  const author = { id: ADMIN.id, displayName: ADMIN.displayName }
  return {
    id: 'w-light',
    slug: 'light-microscopy',
    title: 'Light microscopy',
    summary: '',
    categoryId: null,
    isLanding: false,
    body: '',
    heroMediaId: null,
    status: 'draft',
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

export function categoryFixture(overrides: Partial<Category> = {}): Category {
  return {
    id: 'c-light',
    slug: 'light-microscopy',
    name: 'Light Microscopy',
    description: '',
    parentId: null,
    orderIndex: 2,
    isHidden: false,
    heroMediaId: null,
    imageUrl: null,
    ...overrides,
  }
}

function slugify(title: string, fallback: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
  return slug === '' ? fallback : slug
}

export function createFakeServer(initial: Partial<FakeServerState> = {}) {
  const state: FakeServerState = {
    user: initial.user ?? ADMIN,
    users: initial.users ?? [initial.user ?? ADMIN],
    categories: initial.categories ?? [categoryFixture()],
    guides: initial.guides ?? [guideFixture()],
    pages: initial.pages ?? [],
    media: initial.media ?? [],
    revisions: initial.revisions ?? {},
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

  function noContent(): Response {
    return new Response(null, { status: 204 })
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
      // The server takes this from the first step that carries an image, which
      // is what a browse card shows.
      thumbnailUrl:
        guide.steps.flatMap((step) => step.media).find((item) => item.kind === 'image')?.url ??
        null,
      updatedAt: guide.updatedAt,
      publishedAt: guide.publishedAt,
    }
  }

  function summarisePage(page: Page): PageSummary {
    return {
      id: page.id,
      slug: page.slug,
      title: page.title,
      summary: page.summary,
      categoryId: page.categoryId,
      isLanding: page.isLanding,
      status: page.status,
      heroImageUrl: page.heroMediaId ? `/api/media/${page.heroMediaId}` : null,
      updatedAt: page.updatedAt,
      publishedAt: page.publishedAt,
    }
  }

  /** Readers see published documents only; everyone else sees all but archived. */
  function visible<T extends { status: string }>(documents: T[]): T[] {
    return state.user.role === 'viewer'
      ? documents.filter((document) => document.status === 'published')
      : documents.filter((document) => document.status !== 'archived')
  }

  function nextTimestamp(): string {
    saveCount += 1
    return `2026-07-01T08:${String(saveCount).padStart(2, '0')}:00Z`
  }

  function recordRevision(document: Guide | Page): void {
    const history = state.revisions[document.id] ?? []
    history.push({
      version: document.version,
      publishedAt: document.publishedAt ?? '2026-07-01T09:00:00Z',
      document,
    })
    state.revisions[document.id] = history
  }

  function revisionSummaries(id: string): RevisionSummary[] {
    return (state.revisions[id] ?? []).map((revision) => ({
      version: revision.version,
      publishedAt: revision.publishedAt,
      publishedBy: { id: state.user.id, displayName: state.user.displayName },
    }))
  }

  function handleGuides(path: string, method: string, body: unknown, url: URL): Response | null {
    if (path === '/guides' && method === 'GET') {
      let guides = visible(state.guides)
      const categoryId = url.searchParams.get('categoryId')
      const status = url.searchParams.get('status')
      const authorId = url.searchParams.get('authorId')
      const tags = url.searchParams.get('tags')
      const q = url.searchParams.get('q')

      if (categoryId) guides = guides.filter((guide) => guide.categoryId === categoryId)
      if (status) guides = guides.filter((guide) => guide.status === status)
      if (authorId) guides = guides.filter((guide) => guide.author.id === authorId)
      if (q) guides = guides.filter((guide) => guide.title.toLowerCase().includes(q.toLowerCase()))
      if (tags) {
        /* All of the tags, not any of them — the same rule the real filter
           applies, and the one a wiki page's embedded list depends on. */
        const wanted = tags.split(',').map((tag) => tag.trim()).filter(Boolean)
        guides = guides.filter((guide) => wanted.every((tag) => guide.tags.includes(tag)))
      }
      return json(guides.map(summarise))
    }

    if (path === '/guides' && method === 'POST') {
      const input = body as { title: string; categoryId: string }
      const created = guideFixture({
        id: `g-${state.guides.length + 1}`,
        slug: slugify(input.title, 'guide'),
        title: input.title,
        categoryId: input.categoryId,
        steps: [],
      })
      state.guides.push(created)
      return json(created, 201)
    }

    const single = path.match(/^\/guides\/([^/]+)$/)
    if (single) {
      const key = decodeURIComponent(single[1])
      const guide = state.guides.find((g) => g.id === key || g.slug === key)
      if (!guide) return error('not_found', 'No such guide.', 404)

      if (method === 'GET') return json(guide)

      if (method === 'PUT') {
        if (conflictOnNextSave) {
          conflictOnNextSave = false
          return error('conflict', 'Someone else saved this guide first.', 409)
        }
        const incoming = body as Guide
        const saved: Guide = {
          ...guide,
          ...incoming,
          steps: incoming.steps.map((step, index) => ({ ...step, orderIndex: index })),
          updatedAt: nextTimestamp(),
        }
        state.guides = state.guides.map((g) => (g.id === guide.id ? saved : g))
        return json(saved)
      }

      if (method === 'DELETE') {
        if (state.user.role !== 'admin') return error('forbidden', 'Admins only.', 403)
        state.guides = state.guides.map((g) =>
          g.id === guide.id ? { ...g, status: 'archived' } : g,
        )
        return noContent()
      }
    }

    const lifecycle = path.match(/^\/guides\/([^/]+)\/(publish|unpublish)$/)
    if (lifecycle && method === 'POST') {
      const guide = state.guides.find((g) => g.id === lifecycle[1])
      if (!guide) return error('not_found', 'No such guide.', 404)

      const updated: Guide =
        lifecycle[2] === 'publish'
          ? {
              ...guide,
              status: 'published',
              version: guide.version + 1,
              publishedAt: '2026-07-01T09:00:00Z',
            }
          : { ...guide, status: 'draft' }

      state.guides = state.guides.map((g) => (g.id === guide.id ? updated : g))
      if (lifecycle[2] === 'publish') recordRevision(updated)
      return json(updated)
    }

    const revisions = path.match(/^\/guides\/([^/]+)\/revisions(?:\/(\d+))?$/)
    if (revisions && method === 'GET') {
      if (revisions[2] === undefined) return json(revisionSummaries(revisions[1]))
      const found = (state.revisions[revisions[1]] ?? []).find(
        (revision) => revision.version === Number(revisions[2]),
      )
      return found ? json(found.document) : error('not_found', 'No such revision.', 404)
    }

    return null
  }

  function handlePages(path: string, method: string, body: unknown, url: URL): Response | null {
    if (path === '/pages' && method === 'GET') {
      let pages = visible(state.pages)
      const categoryId = url.searchParams.get('categoryId')
      const status = url.searchParams.get('status')
      if (categoryId) pages = pages.filter((page) => page.categoryId === categoryId)
      if (status) pages = pages.filter((page) => page.status === status)
      return json(pages.map(summarisePage))
    }

    if (path === '/pages' && method === 'POST') {
      const input = body as { title: string; categoryId?: string | null; isLanding?: boolean }
      if (input.isLanding && !input.categoryId) {
        return error('validation_failed', 'A landing page has to belong to a category.', 422)
      }
      if (
        input.isLanding &&
        state.pages.some((page) => page.categoryId === input.categoryId && page.isLanding)
      ) {
        return error('conflict', 'That category already has a landing page.', 409)
      }
      const created = pageFixture({
        id: `w-${state.pages.length + 1}`,
        slug: slugify(input.title, 'page'),
        title: input.title,
        categoryId: input.categoryId ?? null,
        isLanding: input.isLanding ?? false,
      })
      state.pages.push(created)
      return json(created, 201)
    }

    const single = path.match(/^\/pages\/([^/]+)$/)
    if (single) {
      const key = decodeURIComponent(single[1])
      const page = state.pages.find((p) => p.id === key || p.slug === key)
      if (!page) return error('not_found', 'No such page.', 404)

      if (method === 'GET') return json(page)

      if (method === 'PUT') {
        if (conflictOnNextSave) {
          conflictOnNextSave = false
          return error('conflict', 'Someone else saved this page first.', 409)
        }
        const saved: Page = { ...page, ...(body as Page), updatedAt: nextTimestamp() }
        state.pages = state.pages.map((p) => (p.id === page.id ? saved : p))
        return json(saved)
      }

      if (method === 'DELETE') {
        if (state.user.role !== 'admin') return error('forbidden', 'Admins only.', 403)
        state.pages = state.pages.map((p) => (p.id === page.id ? { ...p, status: 'archived' } : p))
        return noContent()
      }
    }

    const lifecycle = path.match(/^\/pages\/([^/]+)\/(publish|unpublish)$/)
    if (lifecycle && method === 'POST') {
      const page = state.pages.find((p) => p.id === lifecycle[1])
      if (!page) return error('not_found', 'No such page.', 404)

      const updated: Page =
        lifecycle[2] === 'publish'
          ? {
              ...page,
              status: 'published',
              version: page.version + 1,
              publishedAt: '2026-07-01T09:00:00Z',
            }
          : { ...page, status: 'draft' }

      state.pages = state.pages.map((p) => (p.id === page.id ? updated : p))
      if (lifecycle[2] === 'publish') recordRevision(updated)
      return json(updated)
    }

    const revisions = path.match(/^\/pages\/([^/]+)\/revisions(?:\/(\d+))?$/)
    if (revisions && method === 'GET') {
      if (revisions[2] === undefined) return json(revisionSummaries(revisions[1]))
      const found = (state.revisions[revisions[1]] ?? []).find(
        (revision) => revision.version === Number(revisions[2]),
      )
      return found ? json(found.document) : error('not_found', 'No such revision.', 404)
    }

    return null
  }

  function handleCategories(path: string, method: string, body: unknown): Response | null {
    if (path === '/categories' && method === 'GET') return json(state.categories)

    if (path === '/categories' && method === 'POST') {
      if (state.user.role !== 'admin') return error('forbidden', 'Admins only.', 403)
      const input = body as Partial<Category> & { name: string }
      const created = categoryFixture({
        id: `c-${state.categories.length + 1}`,
        slug: slugify(input.name, 'category'),
        name: input.name,
        description: input.description ?? '',
        parentId: input.parentId ?? null,
        orderIndex: state.categories.length,
        isHidden: input.isHidden ?? false,
      })
      state.categories.push(created)
      return json(created, 201)
    }

    const landing = path.match(/^\/categories\/([^/]+)\/page$/)
    if (landing && method === 'GET') {
      const page = visible(state.pages).find(
        (candidate) => candidate.categoryId === landing[1] && candidate.isLanding,
      )
      return json(page ?? null)
    }

    const single = path.match(/^\/categories\/([^/]+)$/)
    if (single) {
      const category = state.categories.find((candidate) => candidate.id === single[1])
      if (!category) return error('not_found', 'No such category.', 404)
      if (state.user.role !== 'admin') return error('forbidden', 'Admins only.', 403)

      if (method === 'PATCH') {
        const updated = { ...category, ...(body as Partial<Category>) }
        state.categories = state.categories.map((c) => (c.id === category.id ? updated : c))
        return json(updated)
      }

      if (method === 'DELETE') {
        if (state.categories.some((c) => c.parentId === category.id)) {
          return error('conflict', 'Move or delete the sub-categories first.', 409)
        }
        if (state.guides.some((guide) => guide.categoryId === category.id)) {
          return error('conflict', 'Move the guides in this category somewhere else first.', 409)
        }
        if (state.pages.some((page) => page.categoryId === category.id)) {
          return error('conflict', "Move or delete this category's wiki pages first.", 409)
        }
        state.categories = state.categories.filter((c) => c.id !== category.id)
        return noContent()
      }
    }

    return null
  }

  function handleUsers(path: string, method: string, body: unknown): Response | null {
    if (path === '/users' && method === 'GET') return json(state.users)

    if (path === '/users' && method === 'POST') {
      const input = body as { email: string; displayName: string; role: User['role'] }
      const created: User = {
        id: `u-${state.users.length + 1}`,
        email: input.email,
        displayName: input.displayName,
        role: input.role,
        isActive: true,
        createdAt: '2026-07-01T08:00:00Z',
      }
      state.users.push(created)
      return json(created, 201)
    }

    const single = path.match(/^\/users\/([^/]+)$/)
    if (single && method === 'PATCH') {
      const person = state.users.find((candidate) => candidate.id === single[1])
      if (!person) return error('not_found', 'No such person.', 404)
      const updated = { ...person, ...(body as Partial<User>) }
      state.users = state.users.map((u) => (u.id === person.id ? updated : u))
      return json(updated)
    }

    return null
  }

  function handleDiscovery(path: string, method: string, url: URL): Response | null {
    if (path === '/tags' && method === 'GET') {
      const counts = new Map<string, number>()
      for (const guide of visible(state.guides)) {
        for (const tag of guide.tags) counts.set(tag, (counts.get(tag) ?? 0) + 1)
      }
      const tags: Tag[] = [...counts.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([slug, guideCount]) => ({ id: `t-${slug}`, slug, name: slug, guideCount }))
      return json(tags)
    }

    if (path === '/search' && method === 'GET') {
      const term = (url.searchParams.get('q') ?? '').toLowerCase()
      if (term === '') return json([])
      const hits: SearchResult[] = [
        ...visible(state.guides)
          .filter((guide) => guide.title.toLowerCase().includes(term))
          .map((guide) => ({ kind: 'guide' as const, guide: summarise(guide) })),
        ...visible(state.pages)
          .filter((page) => page.title.toLowerCase().includes(term))
          .map((page) => ({ kind: 'page' as const, page: summarisePage(page) })),
      ]
      return json(hits)
    }

    return null
  }

  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), 'http://reticle.test')
    const path = url.pathname.replace(/^\/api/, '')
    const method = init?.method ?? 'GET'
    const isForm = typeof FormData !== 'undefined' && init?.body instanceof FormData
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body
    /* Recorded with its query string: which listing a screen asked for is part
       of the contract, not an implementation detail. Routing below matches on
       the path alone. */
    requests.push({ method, path: `${path}${url.search}`, body })

    if (path === '/auth/login' && method === 'POST') {
      const credentials = body as { email: string; password: string }
      if (credentials.password !== 'correct-horse-battery') {
        return error('invalid_credentials', 'Email or password is incorrect.', 401)
      }
      authenticated = true
      return json(state.user)
    }

    if (path === '/auth/me') {
      return authenticated ? json(state.user) : error('not_authenticated', 'Not signed in.', 401)
    }

    if (!authenticated) return error('not_authenticated', 'Not signed in.', 401)

    if (path === '/media' && method === 'POST') {
      /* The real endpoint decides image or video from the bytes, so the fake
         reads the uploaded file's type rather than asking the caller. */
      const file = isForm ? ((init!.body as FormData).get('file') as File | null) : null
      const isVideo = file?.type.startsWith('video/') ?? false
      const id = `m-${state.media.length + 1}`
      const uploaded: Media = isVideo
        ? videoFixture({ id, url: `/api/media/${id}`, alt: '', posterUrl: null })
        : imageFixture({ id, url: `/api/media/${id}` })
      state.media.push(uploaded)
      return json(uploaded, 201)
    }

    return (
      handleDiscovery(path, method, url) ??
      handleCategories(path, method, body) ??
      handleGuides(path, method, body, url) ??
      handlePages(path, method, body, url) ??
      handleUsers(path, method, body) ??
      error('not_found', `Fake server has no route for ${method} ${path}`, 404)
    )
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

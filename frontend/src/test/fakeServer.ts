/**
 * An in-memory stand-in for the Reticle backend, used only by tests.
 *
 * This is test scaffolding, not a second implementation of the app: components
 * under test still go through the real `ApiClient` and the real request/response
 * shapes, so a contract mistake surfaces here rather than in production.
 *
 * It follows docs/API.md closely enough for the screens to be exercised — the
 * visibility rule, tag filtering, the `expectedUpdatedAt` check — and no
 * further. Where the real server has detail the UI never sees (ranking, slug
 * transliteration, upload decoding), this does the simplest thing that answers.
 */

import { DEFAULT_UPLOAD_LIMITS, type UploadLimits } from '../domain/media'
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
  UserRef,
} from '../domain/types'

/** One entry of publish history, with the document as it was at that moment. */
export interface FakeRevision<T> {
  version: number
  publishedAt: string
  publishedBy: UserRef
  snapshot: T
}

export interface FakeServerState {
  /** Who the session belongs to; swap it before a login to sign in as someone else. */
  user: User
  users: User[]
  categories: Category[]
  guides: Guide[]
  pages: Page[]
  media: Media[]
  /** Display names for tags, by slug; a tag without one is shown as its slug. */
  tagNames: Record<string, string>
  /** Publish history by guide or page id. Publishing through the API adds to it. */
  revisions: Record<string, FakeRevision<Guide | Page>[]>
  /** What `GET /config` answers; the server's defaults unless a test says otherwise. */
  limits: UploadLimits
}

export interface RecordedRequest {
  method: string
  path: string
  query: URLSearchParams
  body: unknown
}

export function userFixture(overrides: Partial<User> = {}): User {
  return {
    id: 'u-thom',
    email: 'thom.dehoog@zmb.uzh.ch',
    displayName: 'Thom de Hoog',
    role: 'admin',
    isActive: true,
    createdAt: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const ADMIN = userFixture()

export function categoryFixture(overrides: Partial<Category> = {}): Category {
  return {
    id: 'c-light',
    slug: 'light-microscopy',
    name: 'Light Microscopy',
    description: '',
    parentId: null,
    orderIndex: 2,
    isHidden: false,
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
    id: 'p-objectives',
    slug: 'choosing-an-objective',
    title: 'Choosing an objective',
    summary: '',
    categoryId: null,
    isLanding: false,
    body: 'Match the immersion medium to the objective.',
    heroMediaId: null,
    heroAlt: '',
    status: 'published',
    author,
    lastEditedBy: author,
    contributors: [author],
    viewCount: 0,
    createdAt: '2026-07-01T08:00:00Z',
    updatedAt: '2026-07-01T08:00:00Z',
    publishedAt: '2026-07-01T09:00:00Z',
    version: 1,
    ...overrides,
  }
}

function slugify(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function summariseGuide(guide: Guide): GuideSummary {
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

function summarisePage(page: Page): PageSummary {
  return {
    id: page.id,
    slug: page.slug,
    title: page.title,
    summary: page.summary,
    categoryId: page.categoryId,
    isLanding: page.isLanding,
    status: page.status,
    updatedAt: page.updatedAt,
    publishedAt: page.publishedAt,
  }
}

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

const NOT_FOUND = () => error('not_found', 'Not found.', 404)
const FORBIDDEN = () => error('forbidden', 'You are not allowed to do that.', 403)

export function createFakeServer(initial: Partial<FakeServerState> = {}) {
  const user = initial.user ?? ADMIN
  const state: FakeServerState = {
    user,
    users: initial.users ?? [user],
    categories: initial.categories ?? [categoryFixture()],
    guides: initial.guides ?? [guideFixture()],
    pages: initial.pages ?? [],
    media: initial.media ?? [],
    tagNames: initial.tagNames ?? {},
    revisions: initial.revisions ?? {},
    limits: initial.limits ?? { ...DEFAULT_UPLOAD_LIMITS },
  }

  const requests: RecordedRequest[] = []
  let authenticated = true
  let saveCount = 0
  let created = 0
  /** Set by a test to make the next save look like a colleague got there first. */
  let conflictOnNextSave = false
  /** Set by a test to make the next upload fail the way the real server would. */
  let uploadRefusal: Response | null = null

  /** Files a snapshot the way the real server does on every publish. */
  function recordRevision<T extends Guide | Page>(published: T): T {
    state.revisions[published.id] = [
      ...(state.revisions[published.id] ?? []),
      {
        version: published.version,
        publishedAt: published.publishedAt ?? '',
        publishedBy: me(),
        snapshot: published,
      },
    ]
    return published
  }

  /** The two history endpoints, which guides and pages share the shape of. */
  function history(id: string, version: string | undefined): Response {
    if (!isAuthor()) return FORBIDDEN()
    const revisions = state.revisions[id] ?? []
    if (version === undefined) {
      return json(revisions.map(({ snapshot: _snapshot, ...summary }) => summary))
    }
    const found = revisions.find((revision) => String(revision.version) === version)
    return found ? json(found.snapshot) : error('not_found', 'That revision does not exist.', 404)
  }

  /** A fresh, strictly increasing timestamp, so every write changes `updatedAt`. */
  function nextTimestamp(): string {
    saveCount += 1
    return `2026-07-01T08:${String(saveCount).padStart(2, '0')}:00Z`
  }

  const isAuthor = () => state.user.role !== 'viewer'
  const isAdmin = () => state.user.role === 'admin'
  const me = () => ({ id: state.user.id, displayName: state.user.displayName })

  /** The one visibility rule from docs/API.md, applied to guides and pages alike. */
  function visible(item: { status: string }): boolean {
    if (item.status === 'archived') return false
    return isAuthor() || item.status === 'published'
  }

  function findGuide(key: string): Guide | undefined {
    return state.guides.find((guide) => (guide.id === key || guide.slug === key) && visible(guide))
  }

  function findPage(key: string): Page | undefined {
    return state.pages.find((page) => (page.id === key || page.slug === key) && visible(page))
  }

  function replaceGuide(next: Guide): Guide {
    state.guides = state.guides.map((guide) => (guide.id === next.id ? next : guide))
    return next
  }

  function replacePage(next: Page): Page {
    state.pages = state.pages.map((page) => (page.id === next.id ? next : page))
    return next
  }

  function tags(): Tag[] {
    const counts = new Map<string, number>()
    for (const guide of state.guides.filter(visible)) {
      for (const slug of guide.tags) counts.set(slug, (counts.get(slug) ?? 0) + 1)
    }
    return [...counts.entries()]
      .map(([slug, guideCount]) => ({
        id: `t-${slug}`,
        slug,
        name: state.tagNames[slug] ?? slug,
        guideCount,
      }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }

  function matches(text: string, term: string): boolean {
    return text.toLowerCase().includes(term.toLowerCase())
  }

  function listGuides(query: URLSearchParams): GuideSummary[] {
    const wanted = (query.get('tags') ?? '').split(',').filter(Boolean)
    const term = query.get('q')
    return state.guides
      .filter(visible)
      .filter((guide) => !query.get('categoryId') || guide.categoryId === query.get('categoryId'))
      .filter((guide) => !query.get('status') || guide.status === query.get('status'))
      .filter((guide) => !query.get('authorId') || guide.author.id === query.get('authorId'))
      .filter((guide) => wanted.every((slug) => guide.tags.includes(slug)))
      .filter((guide) => !term || matches(`${guide.title} ${guide.summary}`, term))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .map(summariseGuide)
  }

  function listPages(query: URLSearchParams): PageSummary[] {
    const term = query.get('q')
    return state.pages
      .filter(visible)
      .filter((page) => !query.get('categoryId') || page.categoryId === query.get('categoryId'))
      .filter((page) => !query.get('status') || page.status === query.get('status'))
      .filter((page) => !term || matches(`${page.title} ${page.summary}`, term))
      .sort((a, b) => a.title.localeCompare(b.title))
      .map(summarisePage)
  }

  function search(term: string): SearchResult[] {
    if (term.trim() === '') return []
    const guides: SearchResult[] = state.guides
      .filter(visible)
      .filter((guide) =>
        matches(
          [
            guide.title,
            guide.summary,
            ...guide.tags,
            ...guide.steps.flatMap((step) => [step.title, ...step.bullets.map((b) => b.text)]),
          ].join(' '),
          term,
        ),
      )
      .map((guide) => ({ kind: 'guide', guide: summariseGuide(guide) }))
    const pages: SearchResult[] = state.pages
      .filter(visible)
      .filter((page) => matches(`${page.title} ${page.summary} ${page.body}`, term))
      .map((page) => ({ kind: 'page', page: summarisePage(page) }))
    return [...guides, ...pages]
  }

  /** The `expectedUpdatedAt` rule, plus the switch tests use to force a refusal. */
  function refusedAsConflict(stored: { updatedAt: string }, body: unknown, noun: string) {
    const expected = (body as { expectedUpdatedAt?: string }).expectedUpdatedAt
    if (expected === undefined) {
      return error('validation_failed', 'expectedUpdatedAt is required.', 422)
    }
    if (conflictOnNextSave || expected !== stored.updatedAt) {
      conflictOnNextSave = false
      return error('conflict', `Someone else saved this ${noun} first.`, 409)
    }
    return null
  }

  function handle(method: string, path: string, query: URLSearchParams, body: unknown): Response {
    if (path === '/auth/login' && method === 'POST') {
      const credentials = body as { email: string; password: string }
      if (credentials.password !== 'correct-horse-battery') {
        return error('invalid_credentials', 'Email or password is incorrect.', 401)
      }
      authenticated = true
      return json(state.user)
    }

    if (path === '/auth/logout' && method === 'POST') {
      authenticated = false
      return noContent()
    }

    if (!authenticated) return error('not_authenticated', 'Not signed in.', 401)

    if (path === '/auth/me') return json(state.user)

    /* ----------------------------------------------------------- categories */

    if (path === '/categories' && method === 'GET') return json(state.categories)

    if (path === '/categories' && method === 'POST') {
      if (!isAdmin()) return FORBIDDEN()
      const input = body as Partial<Category> & { name: string }
      created += 1
      const category: Category = {
        id: `c-new-${created}`,
        slug: slugify(input.name),
        name: input.name,
        description: input.description ?? '',
        parentId: input.parentId ?? null,
        orderIndex: state.categories.length,
        isHidden: input.isHidden ?? false,
      }
      state.categories = [...state.categories, category]
      return json(category, 201)
    }

    const landingMatch = path.match(/^\/categories\/([^/]+)\/page$/)
    if (landingMatch && method === 'GET') {
      const page = state.pages.find(
        (candidate) =>
          candidate.isLanding && candidate.categoryId === landingMatch[1] && visible(candidate),
      )
      return json(page ?? null)
    }

    const categoryMatch = path.match(/^\/categories\/([^/]+)$/)
    if (categoryMatch) {
      const category = state.categories.find((candidate) => candidate.id === categoryMatch[1])
      if (!category) return NOT_FOUND()
      if (!isAdmin()) return FORBIDDEN()

      if (method === 'PATCH') {
        const changes = body as Partial<Category>
        const updated: Category = {
          ...category,
          ...changes,
          slug: changes.name ? slugify(changes.name) : category.slug,
        }
        state.categories = state.categories.map((c) => (c.id === category.id ? updated : c))
        return json(updated)
      }

      if (method === 'DELETE') {
        const inUse =
          state.guides.some((guide) => guide.categoryId === category.id) ||
          state.pages.some((page) => page.categoryId === category.id) ||
          state.categories.some((child) => child.parentId === category.id)
        if (inUse) {
          return error('conflict', 'This category still holds guides, pages or categories.', 409)
        }
        state.categories = state.categories.filter((c) => c.id !== category.id)
        return noContent()
      }
    }

    /* ----------------------------------------------------------------- tags */

    if (path === '/tags' && method === 'GET') return json(tags())

    /* --------------------------------------------------------------- guides */

    if (path === '/guides' && method === 'GET') return json(listGuides(query))

    if (path === '/guides' && method === 'POST') {
      if (!isAuthor()) return FORBIDDEN()
      const input = body as { title: string; categoryId: string }
      created += 1
      const guide = guideFixture({
        id: `g-new-${created}`,
        slug: slugify(input.title),
        title: input.title,
        categoryId: input.categoryId,
        steps: [],
        author: me(),
        lastEditedBy: me(),
        contributors: [me()],
        updatedAt: nextTimestamp(),
      })
      state.guides = [...state.guides, guide]
      return json(guide, 201)
    }

    const guideAction = path.match(/^\/guides\/([^/]+)\/(publish|unpublish|view)$/)
    if (guideAction && method === 'POST') {
      const guide = findGuide(guideAction[1])
      if (!guide) return NOT_FOUND()

      if (guideAction[2] === 'view') {
        replaceGuide({ ...guide, viewCount: guide.viewCount + 1 })
        return noContent()
      }
      if (!isAuthor()) return FORBIDDEN()
      if (guideAction[2] === 'publish') {
        return json(
          recordRevision(
            replaceGuide({
              ...guide,
              status: 'published',
              version: guide.version + 1,
              publishedAt: '2026-07-01T09:00:00Z',
              updatedAt: nextTimestamp(),
            }),
          ),
        )
      }
      return json(replaceGuide({ ...guide, status: 'draft', updatedAt: nextTimestamp() }))
    }

    const guideHistory = path.match(/^\/guides\/([^/]+)\/revisions(?:\/([^/]+))?$/)
    if (guideHistory && method === 'GET') {
      /* By id only, like the real endpoint: a slug here is a 404. */
      const guide = state.guides.find((candidate) => candidate.id === guideHistory[1])
      return guide && visible(guide) ? history(guide.id, guideHistory[2]) : NOT_FOUND()
    }

    const guideMatch = path.match(/^\/guides\/([^/]+)$/)
    if (guideMatch) {
      const guide = findGuide(decodeURIComponent(guideMatch[1]))
      if (!guide) return NOT_FOUND()

      if (method === 'GET') return json(guide)
      if (!isAuthor()) return FORBIDDEN()

      if (method === 'PUT') {
        const refusal = refusedAsConflict(guide, body, 'guide')
        if (refusal) return refusal
        const incoming = body as Guide
        return json(
          replaceGuide({
            ...guide,
            ...incoming,
            /* Server-owned fields in the body are ignored. */
            id: guide.id,
            slug: guide.slug,
            status: guide.status,
            version: guide.version,
            publishedAt: guide.publishedAt,
            author: guide.author,
            viewCount: guide.viewCount,
            lastEditedBy: me(),
            tags: [...incoming.tags].sort(),
            steps: incoming.steps.map((step, index) => ({ ...step, orderIndex: index })),
            updatedAt: nextTimestamp(),
          }),
        )
      }

      if (method === 'DELETE') {
        if (!isAdmin()) return FORBIDDEN()
        replaceGuide({ ...guide, status: 'archived' })
        return noContent()
      }
    }

    /* ---------------------------------------------------------------- pages */

    if (path === '/pages' && method === 'GET') return json(listPages(query))

    if (path === '/pages' && method === 'POST') {
      if (!isAuthor()) return FORBIDDEN()
      const input = body as { title: string; categoryId?: string | null; isLanding?: boolean }
      created += 1
      const page = pageFixture({
        id: `p-new-${created}`,
        slug: slugify(input.title),
        title: input.title,
        categoryId: input.categoryId ?? null,
        isLanding: input.isLanding ?? false,
        body: '',
        status: 'draft',
        publishedAt: null,
        version: 0,
        author: me(),
        lastEditedBy: me(),
        contributors: [me()],
        updatedAt: nextTimestamp(),
      })
      state.pages = [...state.pages, page]
      return json(page, 201)
    }

    const pageAction = path.match(/^\/pages\/([^/]+)\/(publish|unpublish|view)$/)
    if (pageAction && method === 'POST') {
      const page = findPage(pageAction[1])
      if (!page) return NOT_FOUND()

      if (pageAction[2] === 'view') {
        replacePage({ ...page, viewCount: page.viewCount + 1 })
        return noContent()
      }
      if (!isAuthor()) return FORBIDDEN()
      if (pageAction[2] === 'publish') {
        if (page.title.trim() === '' || page.body.trim() === '') {
          return error('validation_failed', 'A page needs a title and some content.', 422)
        }
        return json(
          recordRevision(
            replacePage({
              ...page,
              status: 'published',
              version: page.version + 1,
              publishedAt: '2026-07-01T09:00:00Z',
              updatedAt: nextTimestamp(),
            }),
          ),
        )
      }
      return json(replacePage({ ...page, status: 'draft', updatedAt: nextTimestamp() }))
    }

    const pageHistory = path.match(/^\/pages\/([^/]+)\/revisions(?:\/([^/]+))?$/)
    if (pageHistory && method === 'GET') {
      const page = state.pages.find((candidate) => candidate.id === pageHistory[1])
      return page && visible(page) ? history(page.id, pageHistory[2]) : NOT_FOUND()
    }

    const pageMatch = path.match(/^\/pages\/([^/]+)$/)
    if (pageMatch) {
      const page = findPage(decodeURIComponent(pageMatch[1]))
      if (!page) return NOT_FOUND()

      if (method === 'GET') return json(page)
      if (!isAuthor()) return FORBIDDEN()

      if (method === 'PUT') {
        const refusal = refusedAsConflict(page, body, 'page')
        if (refusal) return refusal
        const incoming = body as Page
        if (incoming.isLanding && incoming.categoryId === null) {
          return error('validation_failed', 'A landing page needs a category.', 422)
        }
        return json(
          replacePage({
            ...page,
            title: incoming.title,
            summary: incoming.summary,
            body: incoming.body,
            categoryId: incoming.categoryId,
            isLanding: incoming.isLanding,
            heroMediaId: incoming.heroMediaId,
            // As the server does: a description is kept only alongside a hero.
            heroAlt: incoming.heroMediaId ? (incoming.heroAlt ?? '').trim() : '',
            lastEditedBy: me(),
            updatedAt: nextTimestamp(),
          }),
        )
      }

      if (method === 'DELETE') {
        if (!isAdmin()) return FORBIDDEN()
        replacePage({ ...page, status: 'archived' })
        return noContent()
      }
    }

    /* --------------------------------------------------------------- config */

    if (path === '/config' && method === 'GET') return json(state.limits)

    /* --------------------------------------------------------------- search */

    if (path === '/search' && method === 'GET') return json(search(query.get('q') ?? ''))

    /* ---------------------------------------------------------------- media */

    if (path === '/media' && method === 'POST') {
      if (!isAuthor()) return FORBIDDEN()
      if (uploadRefusal) {
        const refusal = uploadRefusal
        uploadRefusal = null
        return refusal
      }
      /* The real server reads the bytes; the browser's declared type is close
         enough for a stand-in. */
      const file = body instanceof FormData ? body.get('file') : null
      const isVideo = file instanceof File && file.type.startsWith('video/')
      const id = `m-${state.media.length + 1}`
      const media: Media = {
        id,
        kind: isVideo ? 'video' : 'image',
        url: `/api/media/${id}`,
        alt: '',
        width: isVideo ? null : 800,
        height: isVideo ? null : 600,
        annotations: [],
      }
      state.media.push(media)
      return json(media, 201)
    }

    /* ---------------------------------------------------------------- users */

    if (path === '/users' && method === 'GET') {
      return isAdmin() ? json(state.users) : FORBIDDEN()
    }

    if (path === '/users' && method === 'POST') {
      if (!isAdmin()) return FORBIDDEN()
      const input = body as Pick<User, 'email' | 'displayName' | 'role'>
      created += 1
      const person = userFixture({
        id: `u-new-${created}`,
        email: input.email,
        displayName: input.displayName,
        role: input.role,
      })
      state.users = [...state.users, person]
      return json(person, 201)
    }

    const userMatch = path.match(/^\/users\/([^/]+)$/)
    if (userMatch && method === 'PATCH') {
      if (!isAdmin()) return FORBIDDEN()
      const person = state.users.find((candidate) => candidate.id === userMatch[1])
      if (!person) return NOT_FOUND()
      const updated = { ...person, ...(body as Partial<User>) }
      state.users = state.users.map((candidate) => (candidate.id === person.id ? updated : candidate))
      return json(updated)
    }

    const passwordMatch = path.match(/^\/users\/([^/]+)\/password$/)
    if (passwordMatch && method === 'POST') {
      const input = body as { currentPassword: string }
      if (input.currentPassword !== 'correct-horse-battery') {
        return error('invalid_credentials', 'Current password is incorrect.', 401)
      }
      return noContent()
    }

    return error('not_found', `Fake server has no route for ${method} ${path}`, 404)
  }

  const fetchImpl = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = new URL(String(input), 'http://reticle.test')
    const path = url.pathname.replace(/^\/api/, '')
    const method = init?.method ?? 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : init?.body
    requests.push({ method, path, query: url.searchParams, body })
    return handle(method, path, url.searchParams, body)
  }) as unknown as typeof fetch

  return {
    fetchImpl,
    state,
    requests,
    get saveCount() {
      return saveCount
    },
    /** Requests seen so far for one method and path, e.g. `count('POST', '/guides/g1/view')`. */
    count(method: string, path: string): number {
      return requests.filter((request) => request.method === method && request.path === path).length
    },
    /** Ends the session server-side, as an expiry or a logout elsewhere would. */
    signOut() {
      authenticated = false
    },
    failNextSaveWithConflict() {
      conflictOnNextSave = true
    },
    /** Makes the next upload fail with the given error, as the server words it. */
    refuseNextUpload(code: string, message: string, status: number) {
      uploadRefusal = error(code, message, status)
    },
    /** A colleague's save: changes a guide and moves its `updatedAt` on. */
    editGuideElsewhere(id: string, changes: Partial<Guide>) {
      const guide = state.guides.find((candidate) => candidate.id === id)
      if (guide) replaceGuide({ ...guide, ...changes, updatedAt: nextTimestamp() })
    },
    editPageElsewhere(id: string, changes: Partial<Page>) {
      const page = state.pages.find((candidate) => candidate.id === id)
      if (page) replacePage({ ...page, ...changes, updatedAt: nextTimestamp() })
    },
  }
}

export type FakeServer = ReturnType<typeof createFakeServer>

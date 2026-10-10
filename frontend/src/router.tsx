/**
 * Every route in Reticle, in one place.
 *
 * Code-based on purpose: there are a dozen and a half routes, and a table that can be read
 * top to bottom is worth more here than a file-naming convention and the build
 * plugin that comes with it.
 *
 * The router is only ever mounted for a signed-in user — `App` shows the login
 * screen at the same URL otherwise — so loaders may assume a session, and the
 * role guards below can read the user straight from the query cache.
 */

import type { QueryClient } from '@tanstack/react-query'
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  notFound,
  redirect,
  type RouterHistory,
} from '@tanstack/react-router'

import { ApiError } from './api/client'
import type { ReticleApi } from './api/reticle'
import { roleAtLeast, sessionQuery } from './auth/session'
import { AppShell } from './components/AppShell'
import { preloadMarkdownBody } from './components/LazyMarkdownBody'
import { NotFound, RouteError, RoutePending } from './components/RouteStates'
import type { Category, Role } from './domain/types'
import { AccountPage } from './pages/AccountPage'
import { CategoryPage } from './pages/CategoryPage'
import { GuideHistoryPage, GuideRevisionPage } from './pages/GuideHistoryPage'
import { GuideViewPage } from './pages/GuideViewPage'
import { HomePage } from './pages/HomePage'
import { PageHistoryPage, PageRevisionPage } from './pages/PageHistoryPage'
import { PageViewPage } from './pages/PageViewPage'
import { SearchPage } from './pages/SearchPage'
import { TagPage } from './pages/TagPage'
import { TagsPage } from './pages/TagsPage'
import { WikiIndexPage } from './pages/WikiIndexPage'
import { categoryQueries } from './queries/categories'
import { guideQueries } from './queries/guides'
import { pageQueries } from './queries/pages'
import { searchQueries } from './queries/search'
import { tagQueries } from './queries/tags'
import { userQueries } from './queries/users'

export interface RouterContext {
  api: ReticleApi
  queryClient: QueryClient
}

/**
 * Sends anyone below `minimum` back to the home page.
 *
 * Cosmetic, like every role check in the frontend: it spares a viewer a screen
 * full of refused requests. The server is what actually says no.
 */
function requireRole({ api, queryClient }: RouterContext, minimum: Role): void {
  const user = queryClient.getQueryData(sessionQuery(api).queryKey)
  if (!user || !roleAtLeast(user.role, minimum)) throw redirect({ to: '/', replace: true })
}

/**
 * Turns the server's `not_found` into the router's, so a missing guide gets the
 * not-found screen rather than an error box. Anything else stays an error.
 */
async function orNotFound<T>(request: Promise<T>): Promise<T> {
  try {
    return await request
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === 'not_found') throw notFound()
    throw cause
  }
}

/**
 * Runs a loader's work, and goes quiet if the session ended underneath it.
 *
 * A 401 mid-load means `App` is already swapping the router for the login
 * screen. Reporting the failure would only flash an error box, and log one, for
 * a screen that is on its way out — so the load is left pending instead, and
 * goes away with the router it belongs to.
 */
function load<T>(context: RouterContext, work: (context: RouterContext) => Promise<T>): Promise<T> {
  return work(context).catch((cause: unknown) => {
    const { api, queryClient } = context
    const signedOut = queryClient.getQueryData(sessionQuery(api).queryKey) === null
    if (signedOut) return new Promise<never>(() => undefined)
    throw cause
  })
}

/**
 * The version number in a history URL. It is typed by hand as often as it is
 * clicked, so anything that is not a plain positive whole number is simply a
 * page that does not exist — it never reaches the server as `NaN`.
 */
function versionFrom(raw: string): number {
  if (!/^[1-9]\d{0,8}$/.test(raw)) throw notFound()
  return Number(raw)
}

/**
 * Options shared by the two editor routes.
 *
 * An editor must open on the server's current copy: its saves carry the
 * `updatedAt` it started from, and starting from a stale one turns the first
 * autosave into a false conflict. So these routes are never preloaded on hover
 * and never served from the router's cache of earlier visits — each entry runs
 * the loader and waits for it.
 */
const ALWAYS_FRESH = { preload: false, staleTime: 0, gcTime: 0 } as const

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: AppShell,
})

/*
 * Loaders warm the query cache and return nothing: the pages read the same
 * queries themselves, so a page shows without a loading flash on arrival and
 * still updates when the cache does. The editors are the exception — they want
 * a one-off copy, not a subscription — and take theirs from the loader.
 */

const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  loader: ({ context }) =>
    load(context, async ({ api, queryClient }) => {
      await Promise.all([
        queryClient.ensureQueryData(categoryQueries.list(api)),
        queryClient.ensureQueryData(guideQueries.list(api)),
        queryClient.ensureQueryData(pageQueries.list(api)),
      ])
    }),
  component: HomePage,
})

const categoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/c/$slug',
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      const bySlug = (categories: Category[]) =>
        categories.find((candidate) => candidate.slug === params.slug)

      /* A category missing from the cached list may simply be newer than the
         cache, so the list is asked for again before the answer is "not found". */
      const category =
        bySlug(await queryClient.ensureQueryData(categoryQueries.list(api))) ??
        bySlug(await queryClient.fetchQuery({ ...categoryQueries.list(api), staleTime: 0 }))
      if (!category) throw notFound()

      const [landing] = await Promise.all([
        queryClient.ensureQueryData(pageQueries.landing(api, category.id)),
        queryClient.ensureQueryData(guideQueries.list(api, { categoryId: category.id })),
        queryClient.ensureQueryData(pageQueries.list(api, { categoryId: category.id })),
      ])
      if (landing) await preloadMarkdownBody()
    }),
  component: CategoryPage,
})

const guideRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/g/$slug',
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      await Promise.all([
        orNotFound(queryClient.ensureQueryData(guideQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
      ])
    }),
  component: GuideViewPage,
})

const guideEditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/g/$id/edit',
  ...ALWAYS_FRESH,
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, ({ api, queryClient }) => {
      void queryClient.prefetchQuery(categoryQueries.list(api))
      void queryClient.prefetchQuery(tagQueries.list(api))
      return orNotFound(
        queryClient.fetchQuery({ ...guideQueries.detail(api, params.id), staleTime: 0 }),
      )
    }),
  component: lazyRouteComponent(() => import('./pages/GuideEditorPage'), 'GuideEditorPage'),
})

/*
 * History is addressed by slug, like the reader it hangs off, but the revision
 * endpoints take an id — so each loader resolves the guide first. Authors only:
 * the server refuses a viewer anyway, and the guard spares them the error.
 */

const guideHistoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/g/$slug/history',
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      const [guide] = await Promise.all([
        orNotFound(queryClient.ensureQueryData(guideQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
      ])
      await queryClient.ensureQueryData(guideQueries.revisions(api, guide.id))
    }),
  component: GuideHistoryPage,
})

const guideRevisionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/g/$slug/v/$version',
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      const version = versionFrom(params.version)
      const [guide] = await Promise.all([
        orNotFound(queryClient.ensureQueryData(guideQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
      ])
      await Promise.all([
        queryClient.ensureQueryData(guideQueries.revisions(api, guide.id)),
        orNotFound(queryClient.ensureQueryData(guideQueries.revision(api, guide.id, version))),
      ])
    }),
  component: GuideRevisionPage,
})

const pageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/w/$slug',
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      await Promise.all([
        orNotFound(queryClient.ensureQueryData(pageQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
        preloadMarkdownBody(),
      ])
    }),
  component: PageViewPage,
})

const pageEditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/w/$id/edit',
  ...ALWAYS_FRESH,
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, ({ api, queryClient }) => {
      void queryClient.prefetchQuery(categoryQueries.list(api))
      void queryClient.prefetchQuery(tagQueries.list(api))
      return orNotFound(
        queryClient.fetchQuery({ ...pageQueries.detail(api, params.id), staleTime: 0 }),
      )
    }),
  component: lazyRouteComponent(() => import('./pages/PageEditorPage'), 'PageEditorPage'),
})

const pageHistoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/w/$slug/history',
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      const [page] = await Promise.all([
        orNotFound(queryClient.ensureQueryData(pageQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
      ])
      await queryClient.ensureQueryData(pageQueries.revisions(api, page.id))
    }),
  component: PageHistoryPage,
})

const pageRevisionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/w/$slug/v/$version',
  beforeLoad: ({ context }) => requireRole(context, 'author'),
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      const version = versionFrom(params.version)
      const [page] = await Promise.all([
        orNotFound(queryClient.ensureQueryData(pageQueries.detail(api, params.slug))),
        queryClient.ensureQueryData(categoryQueries.list(api)),
        preloadMarkdownBody(),
      ])
      await Promise.all([
        queryClient.ensureQueryData(pageQueries.revisions(api, page.id)),
        orNotFound(queryClient.ensureQueryData(pageQueries.revision(api, page.id, version))),
      ])
    }),
  component: PageRevisionPage,
})

/** The index of every wiki page; what makes a standalone article findable. */
const wikiRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/wiki',
  loader: ({ context }) =>
    load(context, async ({ api, queryClient }) => {
      await Promise.all([
        queryClient.ensureQueryData(pageQueries.list(api)),
        queryClient.ensureQueryData(categoryQueries.list(api)),
      ])
    }),
  component: WikiIndexPage,
})

const tagsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/tags',
  loader: ({ context }) =>
    load(context, async ({ api, queryClient }) => {
      await queryClient.ensureQueryData(tagQueries.list(api))
    }),
  component: TagsPage,
})

const tagRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/t/$tag',
  loader: ({ context, params }) =>
    load(context, async ({ api, queryClient }) => {
      await Promise.all([
        queryClient.ensureQueryData(guideQueries.list(api, { tags: params.tag })),
        queryClient.ensureQueryData(tagQueries.list(api)),
      ])
    }),
  component: TagPage,
})

const searchRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/search',
  /**
   * `?q=` is whatever a person typed or pasted into the address bar, so it is
   * read defensively: anything that is not text counts as no search at all.
   */
  validateSearch: (search: Record<string, unknown>): { q: string } => ({
    q: typeof search.q === 'string' ? search.q.trim() : '',
  }),
  loaderDeps: ({ search }) => ({ q: search.q }),
  loader: ({ context, deps }) =>
    load(context, async ({ api, queryClient }) => {
      await queryClient.ensureQueryData(searchQueries.results(api, deps.q))
    }),
  component: SearchPage,
})

const accountRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/account',
  component: AccountPage,
})

const usersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/users',
  beforeLoad: ({ context }) => requireRole(context, 'admin'),
  loader: ({ context }) =>
    load(context, async ({ api, queryClient }) => {
      await queryClient.ensureQueryData(userQueries.list(api))
    }),
  component: lazyRouteComponent(() => import('./pages/UsersPage'), 'UsersPage'),
})

/** Any address that is not one of the above goes home, as it always has. */
const unknownRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '$',
  beforeLoad: () => {
    throw redirect({ to: '/', replace: true })
  },
})

const routeTree = rootRoute.addChildren([
  homeRoute,
  categoryRoute,
  guideRoute,
  guideEditRoute,
  guideHistoryRoute,
  guideRevisionRoute,
  pageRoute,
  pageEditRoute,
  pageHistoryRoute,
  pageRevisionRoute,
  wikiRoute,
  tagsRoute,
  tagRoute,
  searchRoute,
  accountRoute,
  usersRoute,
  unknownRoute,
])

/**
 * Search parameters as plain `key=value` text.
 *
 * The router's default encodes values as JSON, which would turn a search for
 * `488` into the number 488 on the way in and write a search for "488" back
 * out as `?q=%22488%22`. The only parameter Reticle has is free text, and its
 * URLs are typed and shared by people, so text is what it stays.
 */
function parseSearch(searchString: string): Record<string, string> {
  return Object.fromEntries(new URLSearchParams(searchString))
}

function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
  }
  const rendered = params.toString()
  return rendered === '' ? '' : `?${rendered}`
}

export function createAppRouter(context: RouterContext, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context,
    history,
    parseSearch,
    stringifySearch,
    scrollRestoration: true,
    /* Hovering a link starts its loader, so the click usually lands on data
       that is already there. The query cache decides what is fresh, hence no
       second layer of freshness here. */
    defaultPreload: 'intent',
    defaultPreloadStaleTime: 0,
    /* A spinner that flashes for a tenth of a second reads as a glitch. Wait
       briefly before showing one; most navigations finish first. */
    defaultPendingMs: 200,
    defaultPendingMinMs: 300,
    defaultPendingComponent: RoutePending,
    defaultErrorComponent: RouteError,
    defaultNotFoundComponent: NotFound,
  })
}

export type AppRouter = ReturnType<typeof createAppRouter>

declare module '@tanstack/react-router' {
  interface Register {
    router: AppRouter
  }
}

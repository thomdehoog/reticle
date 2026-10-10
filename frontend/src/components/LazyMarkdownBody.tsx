import { Suspense, lazy, type ComponentType } from 'react'

/**
 * `MarkdownBody`, loaded on demand.
 *
 * The Markdown parser is the largest thing in the app after React itself, and
 * most visits — the home page, a category, a guide — never render a line of
 * Markdown. Keeping it out of the first download makes it a cost of reading the
 * wiki rather than of opening Reticle.
 */

type Body = ComponentType<{ body: string }>

/** Set once the chunk has arrived, so later renders need not wait even a tick. */
let loaded: Body | null = null

function importMarkdownBody(): Promise<Body> {
  return import('./MarkdownBody').then((module) => {
    loaded = module.MarkdownBody
    return module.MarkdownBody
  })
}

const Deferred = lazy(() => importMarkdownBody().then((component) => ({ default: component })))

/**
 * Starts the download. Route loaders await this alongside their data, so by
 * the time a wiki page renders the parser is already there: the page appears
 * whole, instead of its frame first and its text a moment later.
 */
export function preloadMarkdownBody(): Promise<unknown> {
  return loaded ? Promise.resolve() : importMarkdownBody()
}

export function LazyMarkdownBody({ body }: { body: string }) {
  if (loaded) {
    const Loaded = loaded
    return <Loaded body={body} />
  }

  /* Only reached if something renders Markdown without preloading it first. */
  return (
    <Suspense fallback={null}>
      <Deferred body={body} />
    </Suspense>
  )
}

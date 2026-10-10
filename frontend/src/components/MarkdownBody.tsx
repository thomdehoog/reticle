/**
 * Renders wiki page content.
 *
 * Markdown is rendered to React elements, never to an HTML string — so there is
 * no `dangerouslySetInnerHTML`, no sanitiser to keep up to date, and no way for
 * a guide author to inject script into a colleague's browser. Raw HTML in the
 * source is ignored by design.
 *
 * The one extension is a guide-list block, which is how a wiki page pulls in
 * guides by tag:
 *
 *     ```guidelist
 *     tags: stellaris, confocal
 *     ```
 *
 * That is the mechanism ZMB's category pages are built from — guides live in
 * holding categories and surface wherever a page asks for their tag.
 */

import { useQuery } from '@tanstack/react-query'
import { useRouter } from '@tanstack/react-router'
import { useMemo, type MouseEvent, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { useApi } from '../api/context'
import { guideQueries } from '../queries/guides'
import { GuideRow } from './GuideRow'
import { EmptyState, ErrorAlert } from './ui'

export interface GuideListSpec {
  tags: string[]
  heading: string | null
  limit: number | null
}

/** Parses the `key: value` lines inside a guidelist block. */
export function parseGuideListSpec(source: string): GuideListSpec {
  const spec: GuideListSpec = { tags: [], heading: null, limit: null }

  for (const line of source.split('\n')) {
    const separator = line.indexOf(':')
    if (separator === -1) continue

    const key = line.slice(0, separator).trim().toLowerCase()
    const value = line.slice(separator + 1).trim()

    if (key === 'tags') {
      spec.tags = value
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean)
    } else if (key === 'heading') {
      spec.heading = value || null
    } else if (key === 'limit') {
      const parsed = Number.parseInt(value, 10)
      spec.limit = Number.isFinite(parsed) && parsed > 0 ? parsed : null
    }
  }

  return spec
}

/** The server rejects a `tags` query parameter longer than this outright. */
const MAX_TAG_QUERY_LENGTH = 800

const GUIDELIST_CLASS = 'language-guidelist'

function GuideListEmbed({ source }: { source: string }) {
  const api = useApi()
  const spec = useMemo(() => parseGuideListSpec(source), [source])
  const tagKey = spec.tags.join(',')
  const askable = tagKey !== '' && tagKey.length <= MAX_TAG_QUERY_LENGTH

  const { data, error, isPending } = useQuery({
    ...guideQueries.list(api, { tags: tagKey }),
    enabled: askable,
  })

  if (tagKey === '') {
    return (
      <div className="alert alert--warning">
        This guide list has no tags set, so it cannot show anything yet.
      </div>
    )
  }

  /* Said plainly instead of sent: dropping tags to fit would quietly widen the
     list — a guide must carry *all* of them — and sending them all gets a bare
     validation error from the server in place of a list. */
  if (!askable) {
    return (
      <div className="alert alert--warning">
        This guide list asks for more tags than can be looked up at once. Split it into several
        lists with fewer tags each.
      </div>
    )
  }

  const guides = spec.limit ? (data ?? []).slice(0, spec.limit) : (data ?? [])

  return (
    <section className="guidelist">
      {spec.heading && <h3 className="guidelist__heading">{spec.heading}</h3>}
      <ErrorAlert error={error} />
      {isPending && <p className="save-state">Loading guides…</p>}
      {!isPending && !error && guides.length === 0 && (
        <EmptyState>No published guides tagged “{spec.tags.join('”, “')}” yet.</EmptyState>
      )}
      {guides.length > 0 && (
        <div className="card">
          {guides.map((guide) => (
            <GuideRow key={guide.id} guide={guide} />
          ))}
        </div>
      )}
    </section>
  )
}

/**
 * Whether an author-written link points into the app itself.
 *
 * "Starts with a slash" is not the test: `//host` and `/\host` are both read by
 * browsers as another site, and `/api/…` is a file the server sends, not a
 * screen the router can draw.
 */
export function isInAppPath(href: string): boolean {
  if (!href.startsWith('/')) return false
  if (href.startsWith('//') || href.startsWith('/\\')) return false
  return !href.startsWith('/api/')
}

function isPlainLeftClick(event: MouseEvent): boolean {
  return (
    event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey
  )
}

/**
 * A link in page content.
 *
 * The router's own `Link` only accepts routes it knows at compile time, and
 * what an author typed is neither known nor trustworthy. So an in-app path is
 * drawn as an ordinary anchor — middle-click and "copy link" keep working —
 * and a plain click is handed to the router's history instead of the browser.
 * The router then treats it like any typed-in URL: a real route renders without
 * a reload, and a path that matches nothing falls back to the home page.
 */
function MarkdownLink({ href, children }: { href?: string; children?: ReactNode }) {
  const router = useRouter()

  /* react-markdown blanks a URL it refuses (`javascript:` and the like). An
     anchor with an empty href is a link to the current page, so the text is
     kept and the link is not. */
  if (!href) return <span>{children}</span>

  if (isInAppPath(href)) {
    return (
      <a
        href={href}
        onClick={(event) => {
          if (event.defaultPrevented || !isPlainLeftClick(event)) return
          event.preventDefault()
          router.history.push(href)
        }}
      >
        {children}
      </a>
    )
  }

  if (href.startsWith('#')) return <a href={href}>{children}</a>

  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  )
}

const COMPONENTS: Components = {
  a: MarkdownLink,

  /* For the same reason as the empty href above: `<img src="">` asks the
     browser for the current page again. */
  img({ src, alt }) {
    if (!src) return null
    return <img src={src} alt={alt ?? ''} loading="lazy" />
  },

  /**
   * A fenced block arrives as `<pre><code>`. For a guide list the `<pre>` has
   * to go: it would style the embedded list as source code, and block content
   * inside `<pre>` is not valid HTML in the first place.
   */
  pre({ node, children, ...rest }) {
    const only = node?.children[0]
    const classes =
      only?.type === 'element' && only.tagName === 'code' ? only.properties.className : undefined
    if (Array.isArray(classes) && classes.includes(GUIDELIST_CLASS)) return <>{children}</>
    return <pre {...rest}>{children}</pre>
  },

  code({ node: _node, className, children, ...rest }) {
    if (className === GUIDELIST_CLASS) {
      return <GuideListEmbed source={String(children)} />
    }
    return (
      <code className={className} {...rest}>
        {children}
      </code>
    )
  },
}

const REMARK_PLUGINS = [remarkGfm]

export function MarkdownBody({ body }: { body: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={COMPONENTS}>
        {body}
      </ReactMarkdown>
    </div>
  )
}

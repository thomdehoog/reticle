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
 *
 * The same page is shown in two places, and one of them wants the prose without
 * the lists: see `hideGuideLists`.
 */

import { Children, isValidElement, useMemo } from 'react'
import type { Root, RootContent } from 'mdast'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router'
import remarkGfm from 'remark-gfm'

import { useApi, useAuth } from '../auth/AuthContext'
import type { Guide, GuideSummary } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { GuideRow, GuideRows } from './BrowseCards'
import { EmptyState, ErrorAlert } from './ui'

/** The fence language that marks a guide-list block. */
const GUIDE_LIST_LANGUAGE = 'language-guidelist'

/** The same fence as the parser sees it, before it becomes a class name. */
const GUIDE_LIST_FENCE = 'guidelist'

/** The fence that names one guide, by slug. */
const GUIDE_LANGUAGE = 'language-guide'

function isGuideList(node: RootContent | undefined): boolean {
  return node?.type === 'code' && node.lang === GUIDE_LIST_FENCE
}

/**
 * Whether everything a heading covers is guide lists, and there is at least
 * one. A heading nobody has written under yet is somebody's work in progress
 * and stays.
 */
function holdsOnlyGuideLists(nodes: RootContent[], from: number, depth: number): boolean {
  let found = false
  for (let index = from; index < nodes.length; index += 1) {
    const node = nodes[index]
    if (node.type === 'heading') {
      if (node.depth <= depth) break
      if (!holdsOnlyGuideLists(nodes, index + 1, node.depth)) return false
      continue
    }
    if (!isGuideList(node)) return false
    found = true
  }
  return found
}

/**
 * Drops the guide lists, and the headings whose only content they were.
 *
 * A list arrives with a heading over it — "Starting up" written above the
 * block, and the block's own `heading:` written inside it — so removing the
 * list alone leaves a heading with nothing under it, which reads as a page that
 * failed to load. The heading goes with its list on purpose: if you are here
 * because a heading went missing from a category page, that heading belonged to
 * a list this page is not showing, and putting it back is not the fix.
 *
 * It works on the parsed document rather than on the markdown text. A regular
 * expression over what an author wrote eventually eats a code sample that
 * merely mentions the word.
 */
function remarkWithoutGuideLists() {
  return (tree: Root) => {
    tree.children = tree.children.filter(
      (node, index) =>
        !isGuideList(node) &&
        !(node.type === 'heading' && holdsOnlyGuideLists(tree.children, index + 1, node.depth)),
    )
  }
}

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

/**
 * One named guide, rendered as the row it would be in any list.
 *
 * ZMB's wiki pages are built out of these: a sentence, then the one guide that
 * answers it, then another sentence. Their "access your data" page is nothing
 * but "Windows:" followed by a guide, "Mac:" followed by a guide.
 *
 * Selected by slug rather than by id. A slug is what the URL already shows and
 * what an author can read back to check; an id is a number nobody can verify by
 * looking at it.
 */
function GuideEmbed({ source }: { source: string }) {
  const api = useApi()
  const { can } = useAuth()
  const slug = source.trim().split('\n')[0].trim()

  const { data, error, loading } = useAsync(
    () => (slug === '' ? Promise.resolve(null) : api.getGuide(slug).then(asGuide, () => null)),
    [api, slug],
  )

  if (loading) return <p className="save-state">Loading guide…</p>

  /*
   * A slug that resolves to nothing fails loudly to an author and silently to a
   * reader. An author has to know their link is broken — it is the only way it
   * ever gets fixed. A reader must not be shown a dead entry, and must not be
   * told that a guide exists which they are not allowed to open: "no such
   * guide" and "not yours to see" have to look identical from outside.
   */
  if (!data) {
    if (!can('author')) return null
    return (
      <div className="alert alert--warning">
        No guide has the address “{slug}”. This link shows nothing to a reader.
      </div>
    )
  }

  return (
    <section className="guidelist">
      <ErrorAlert error={error} />
      <GuideRows>
        <GuideRow guide={asSummary(data)} />
      </GuideRows>
    </section>
  )
}

/**
 * A response that is shaped like a guide, or nothing.
 *
 * `getGuide` is typed as returning one, and at runtime it returns whatever
 * arrived. A 200 carrying something else — a proxy's error page, a stub in a
 * test, a future endpoint that answers differently — used to reach `asSummary`,
 * which read `.steps.length` off it and threw inside render. A row that cannot
 * be drawn is the same outcome as a slug that matches nothing, and is handled
 * in the one place that already handles it.
 */
function asGuide(value: unknown): Guide | null {
  const guide = value as Guide | null
  return guide && typeof guide.slug === 'string' && Array.isArray(guide.steps) ? guide : null
}

/**
 * The listing view of a guide we happen to have in full.
 *
 * Fetching one guide by slug returns the whole thing, steps and all, while the
 * row wants the summary a listing would have given. The two derived fields are
 * derived the same way the server derives them — the step count, and the first
 * picture of the first step as the thumbnail — so an embedded row is
 * indistinguishable from the same guide in any other list.
 */
function asSummary(guide: Guide): GuideSummary {
  return {
    ...guide,
    stepCount: guide.steps.length,
    thumbnailUrl: guide.steps.flatMap((step) => step.media)[0]?.url ?? null,
  }
}

function GuideListEmbed({ source }: { source: string }) {
  const api = useApi()
  const spec = useMemo(() => parseGuideListSpec(source), [source])
  const tagKey = spec.tags.join(',')

  const { data, error, loading } = useAsync(
    () => (tagKey === '' ? Promise.resolve([]) : api.listGuides({ tags: tagKey })),
    [api, tagKey],
  )

  if (tagKey === '') {
    return (
      <div className="alert alert--warning">
        This guide list has no tags set, so it cannot show anything yet.
      </div>
    )
  }

  const guides = spec.limit ? (data ?? []).slice(0, spec.limit) : (data ?? [])

  return (
    <section className="guidelist">
      {spec.heading && <h3 className="guidelist__heading">{spec.heading}</h3>}
      <ErrorAlert error={error} />
      {loading && <p className="save-state">Loading guides…</p>}
      {/* Not "no published guides": for an author this listing includes their
          own drafts, and the block requires *all* of the tags rather than any
          of them, which is the usual reason an embed comes back empty. */}
      {!loading && !error && guides.length === 0 && (
        <EmptyState>
          {spec.tags.length === 1
            ? `No guides are tagged “${spec.tags[0]}” yet.`
            : `No guides carry all of “${spec.tags.join('”, “')}” yet.`}
        </EmptyState>
      )}
      {guides.length > 0 && (
        <GuideRows>
          {guides.map((guide) => (
            <GuideRow key={guide.id} guide={guide} />
          ))}
        </GuideRows>
      )}
    </section>
  )
}

/**
 * Keeps in-app links inside the router so a click does not reload the page.
 *
 * "Starts with a slash" is not the same test as "is one of ours".
 * `//evil.example.com/login` starts with a slash and is an entirely different
 * host: treated as an internal route it would render as a plain link, without
 * `target="_blank"` or `rel="noopener"`, and a reader who middle-clicked it
 * would leave the institute's site for somebody else's login form that the
 * author believed was an internal path.
 */
function isInternalPath(href: string): boolean {
  return href.startsWith('/') && !href.startsWith('//')
}

function MarkdownLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  if (href && isInternalPath(href)) {
    return <Link to={href}>{children}</Link>
  }
  /**
   * react-markdown neutralises a URL it rejects — `javascript:` and friends —
   * by rewriting it to the empty string, and `<a href="">` links to the current
   * page. A reader who clicked the hostile link would reload the wiki page and
   * lose their place, which looks like a bug in Reticle rather than like the
   * refusal it is. Rendering the text without a link says the truth: there is
   * nowhere to go.
   */
  if (!href) return <>{children}</>

  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  )
}

/** Same rule for images: an empty source re-requests the whole page. */
function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  if (!src) return null
  return <img src={src} alt={alt ?? ''} loading="lazy" />
}

/**
 * `hideGuideLists` shows the page's prose without its embedded listings, which
 * is what a category with sub-categories underneath it wants: the lists belong
 * to the level below, but the prose above them — at ZMB, what you have to do
 * before your first session — exists nowhere else.
 */
export function MarkdownBody({
  body,
  wide = false,
  hideGuideLists = false,
}: {
  body: string
  wide?: boolean
  hideGuideLists?: boolean
}) {
  return (
    <div className={`markdown${wide ? ' markdown--wide' : ''}`}>
      <ReactMarkdown
        remarkPlugins={hideGuideLists ? [remarkGfm, remarkWithoutGuideLists] : [remarkGfm]}
        components={{
          a: MarkdownLink,
          img: MarkdownImage,
          /**
           * A guide list has to escape the code block it is written inside.
           *
           * Markdown gives a fenced block as `<pre><code>`, and replacing only
           * the `code` leaves the embed inside the `pre` — so the guide rows
           * inherited the monospace font and the grey gutter of a code sample,
           * and the most prominent thing on every category page looked like
           * something that had failed to render.
           */
          pre({ children }) {
            const first = Children.toArray(children)[0]
            if (isValidElement<{ className?: string }>(first)) {
              if (
                first.props.className === GUIDE_LIST_LANGUAGE ||
                first.props.className === GUIDE_LANGUAGE
              ) {
                return <>{first}</>
              }
            }
            return <pre>{children}</pre>
          },
          code({ className, children, ...rest }) {
            if (className === GUIDE_LIST_LANGUAGE) {
              return <GuideListEmbed source={String(children)} />
            }
            if (className === GUIDE_LANGUAGE) {
              return <GuideEmbed source={String(children)} />
            }
            return (
              <code className={className} {...rest}>
                {children}
              </code>
            )
          },
        }}
      >
        {body}
      </ReactMarkdown>
    </div>
  )
}

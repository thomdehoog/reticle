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

import { Children, isValidElement, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import remarkGfm from 'remark-gfm'

import { useApi } from '../auth/AuthContext'
import { useAsync } from '../hooks/useAsync'
import { GuideCard, TileGrid } from './BrowseCards'
import { EmptyState, ErrorAlert } from './ui'

/** The fence language that marks a guide-list block. */
const GUIDE_LIST_LANGUAGE = 'language-guidelist'

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
        <TileGrid>
          {guides.map((guide) => (
            <GuideCard key={guide.id} guide={guide} />
          ))}
        </TileGrid>
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

export function MarkdownBody({ body, wide = false }: { body: string; wide?: boolean }) {
  return (
    <div className={`markdown${wide ? ' markdown--wide' : ''}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
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
              if (first.props.className === GUIDE_LIST_LANGUAGE) return <>{first}</>
            }
            return <pre>{children}</pre>
          },
          code({ className, children, ...rest }) {
            if (className === GUIDE_LIST_LANGUAGE) {
              return <GuideListEmbed source={String(children)} />
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

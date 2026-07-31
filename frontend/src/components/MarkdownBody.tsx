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

import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import remarkGfm from 'remark-gfm'

import { useApi } from '../auth/AuthContext'
import { useAsync } from '../hooks/useAsync'
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
      {!loading && !error && guides.length === 0 && (
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

/** Keeps in-app links inside the router so a click does not reload the page. */
function MarkdownLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  if (href && href.startsWith('/')) {
    return <Link to={href}>{children}</Link>
  }
  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  )
}

export function MarkdownBody({ body }: { body: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: MarkdownLink,
          code({ className, children, ...rest }) {
            if (className === 'language-guidelist') {
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

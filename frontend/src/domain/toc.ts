/**
 * The sections of a wiki page, read from its markdown.
 *
 * One module owns both halves of an agreement: the rail lists a page's
 * sections and the rendered page carries an id on each heading, and the two
 * have to name every section identically or the links go nowhere. Everything
 * here parses with remark — the same parser family the renderer uses — never
 * with a regular expression over source text, which would eventually mistake
 * a code sample's `#` line for a heading.
 *
 * Anchors wear an `s-` prefix so they can never collide with the `group-…`
 * anchors the category pages hand out ([[groups.ts]] `groupAnchor`): the two
 * kinds share the address bar's hash.
 */

import type { Heading, Nodes } from 'mdast'
import remarkGfm from 'remark-gfm'
import remarkParse from 'remark-parse'
import { unified } from 'unified'

export interface PageSection {
  /** The anchor the rendered heading carries and the rail's link points at. */
  id: string
  /** The heading's words, read through any inline formatting. */
  text: string
  /** The heading level as written, 1–3. */
  depth: number
  /** The source line the heading starts on, for pairing ids to rendered headings. */
  line: number
}

/**
 * Three levels, because the rail is a list of places rather than an outline:
 * a column that transcribes every nuance stops being one glance. Deeper
 * headings still render — they are simply not places the rail offers.
 */
const DEEPEST_LISTED = 3

/** The words of a heading, through bold, links, code and whatever else wraps them. */
function headingText(node: Nodes): string {
  if (node.type === 'text' || node.type === 'inlineCode') return node.value
  if ('children' in node) return node.children.map(headingText).join('')
  return ''
}

/**
 * Lowercased, with everything that is not a letter or a number folded into
 * single hyphens. Unicode letters stay: ZMB writes German, and an anchor that
 * dropped the umlauts would collide "Objektträger" with "Objekttrager".
 */
function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
}

/** Every heading in the tree, wherever it sits — a heading inside a blockquote renders too. */
function headings(node: Nodes, found: Heading[]): Heading[] {
  if (node.type === 'heading') found.push(node)
  else if ('children' in node) for (const child of node.children) headings(child as Nodes, found)
  return found
}

export function pageSections(body: string): PageSection[] {
  const tree = unified().use(remarkParse).use(remarkGfm).parse(body)

  const taken = new Map<string, number>()
  const sections: PageSection[] = []

  for (const heading of headings(tree, [])) {
    if (heading.depth > DEEPEST_LISTED) continue

    const text = headingText(heading)
    const base = `s-${slugify(text)}`
    /* Two sections may share a name — "Shutdown" under two instruments — and
       the second must still be reachable on its own. */
    const seen = taken.get(base) ?? 0
    taken.set(base, seen + 1)

    sections.push({
      id: seen === 0 ? base : `${base}-${seen + 1}`,
      text,
      depth: heading.depth,
      line: heading.position?.start.line ?? 0,
    })
  }

  return sections
}

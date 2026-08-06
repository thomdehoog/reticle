/**
 * How a section's contents are arranged on its page.
 *
 * ZMB navigates by tag, not by the category tree: a document sits in one section
 * and carries many tags, and it is the tag that answers "which of these is
 * about the spinning disk". So the bottom of the tree shows its contents under
 * those tags, and a guide that applies to several instruments appears under
 * each of them — which is not duplication, it is the whole reason the site is
 * arranged this way. One LAS X guide belongs under every instrument it applies
 * to, and a reader standing at one of them should not have to know that.
 *
 * **A group holds either kind.** A row points at an endpoint, and the endpoint
 * is a guide or a wiki — the article about the Nikon belongs beside the
 * procedures for it, under `nikon`, because that is what a reader looking for
 * the Nikon wants in front of them. Wikis used to be one lump of their own at
 * the top of the page, which was not a decision about how to arrange them so
 * much as the only thing possible while a page could not carry a tag.
 *
 * Within a group the wikis come first, for the reason they used to come first
 * on the page: they answer "which of these do I want" and the guides answer
 * "how", so reading precedes doing at whatever scale the two sit together.
 *
 * The heading is the tag's own name. Today that is the slug ZMB typed — `osd`,
 * `confocal` — because nothing has ever set a display form. Giving a tag a
 * readable name is a one-field edit rather than markdown surgery, which is the
 * point of arranging the page from data rather than from prose.
 *
 * Documents carrying no tag are not put under an invented heading. They come
 * first, in the order the listing gave them, because a section too small to
 * have been grouped yet is an ordinary state and not a defect to label.
 */

import type { GuideSummary, PageSummary } from './types'

/**
 * One row on a section's page: what it points at, and what groups it.
 *
 * `id` and `tags` are lifted out of the two summaries so that grouping — and
 * the drag that changes a group — never has to ask which kind it is holding.
 * Only the drawing does, and there the union makes the answer exhaustive.
 */
export type Endpoint =
  | { kind: 'guide'; id: string; tags: string[]; guide: GuideSummary }
  | { kind: 'wiki'; id: string; tags: string[]; page: PageSummary }

export interface Group {
  /** The tag, which is both the heading and the identity of the group. */
  tag: string
  items: Endpoint[]
}

export interface Grouped {
  /** Documents with no tag at all, shown above the groups under no heading. */
  loose: Endpoint[]
  groups: Group[]
}

/** A key no two rows on the page can share, since the two kinds mint ids apart. */
export function endpointKey(endpoint: Endpoint): string {
  return `${endpoint.kind}-${endpoint.id}`
}

/**
 * A tag as a heading: its own text, with a capital on the front.
 *
 * The tag is a slug — `nikonti2`, `thunder` — because that is what the URL and
 * the identity are, and lower-case is right there. As the title over a group of
 * procedures it reads as an unfinished label rather than a name, so the first
 * letter is raised and nothing else is touched.
 *
 * Only the first letter. Capitalising every word would turn `carbon-on-mica`
 * into `Carbon-On-Mica`, which is not how anybody writes it, and the CSS
 * `capitalize` keyword does exactly that in some browsers and not others.
 *
 * This is display only. Everything that identifies the tag — the link, the
 * grouping key — keeps the slug, so a nicer name is still a thing an
 * administrator sets on the tag rather than something a stylesheet invents.
 */
export function groupHeading(tag: string): string {
  return tag.charAt(0).toUpperCase() + tag.slice(1)
}

/**
 * The id a group carries on the section page, so the rail can point at it.
 *
 * The rail lists a section's groups and the page draws them, and the two have
 * to agree on a name for each one or the links go nowhere. Derived from the tag
 * in one place rather than spelled out at both ends.
 */
export function groupAnchor(tag: string): string {
  return `group-${tag}`
}

/**
 * The section's guides and wikis, gathered under the tags they carry.
 *
 * The pages passed in are the section's articles — the landing page is the
 * section rather than something inside it, and the caller drops it before
 * getting here for the same reason it is not drawn as a row.
 *
 * `order` is the section's own running order, the groups an administrator has
 * placed. Anything not in it follows, alphabetically — which is where a group
 * nobody has placed belongs: at the bottom, rather than appearing in the middle
 * of an arrangement somebody made.
 */
export function groupDocuments(
  guides: GuideSummary[],
  pages: PageSummary[],
  order: string[] = [],
): Grouped {
  const endpoints: Endpoint[] = [
    ...pages.map(
      (page): Endpoint => ({ kind: 'wiki', id: page.id, tags: page.tags, page }),
    ),
    ...guides.map(
      (guide): Endpoint => ({ kind: 'guide', id: guide.id, tags: guide.tags, guide }),
    ),
  ]

  const byTag = new Map<string, Endpoint[]>()
  const loose: Endpoint[] = []

  for (const endpoint of endpoints) {
    if (endpoint.tags.length === 0) {
      loose.push(endpoint)
      continue
    }
    for (const tag of endpoint.tags) {
      const members = byTag.get(tag)
      if (members) members.push(endpoint)
      else byTag.set(tag, [endpoint])
    }
  }

  /* Placed groups first, in the order they were placed; the rest alphabetically
     after them. Alphabetical alone is nobody's running order — start-up,
     acquisition, shutdown is the sequence somebody works in, and sorting it
     gives `acquisition, shutdown, start-up` — but it is the right fallback,
     because an arrangement that changed with whichever guide happened to be
     imported first is one a reader cannot learn. */
  const placed = new Map(order.map((tag, index) => [tag, index]))
  const groups = [...byTag.entries()]
    .map(([tag, items]) => ({ tag, items }))
    .sort((a, b) => {
      const first = placed.get(a.tag)
      const second = placed.get(b.tag)
      if (first !== undefined && second !== undefined) return first - second
      if (first !== undefined) return -1
      if (second !== undefined) return 1
      return a.tag.localeCompare(b.tag)
    })

  return { loose, groups }
}

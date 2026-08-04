/**
 * How a section's guides are arranged on its page.
 *
 * ZMB navigates by tag, not by the category tree: a guide sits in one section
 * and carries many tags, and it is the tag that answers "which of these is
 * about the spinning disk". So the bottom of the tree shows its guides under
 * those tags, and a guide that applies to several instruments appears under
 * each of them — which is not duplication, it is the whole reason the site is
 * arranged this way. One LAS X guide belongs under every instrument it applies
 * to, and a reader standing at one of them should not have to know that.
 *
 * The heading is the tag's own name. Today that is the slug ZMB typed — `osd`,
 * `confocal` — because nothing has ever set a display form. Giving a tag a
 * readable name is a one-field edit rather than markdown surgery, which is the
 * point of arranging the page from data rather than from prose.
 *
 * Guides carrying no tag are not put under an invented heading. They come
 * first, in the order the listing gave them, because a section too small to
 * have been grouped yet is an ordinary state and not a defect to label.
 */

import type { GuideSummary } from './types'

export interface GuideGroup {
  /** The tag, which is both the heading and the identity of the group. */
  tag: string
  guides: GuideSummary[]
}

export interface GroupedGuides {
  /** Guides with no tag at all, shown above the groups under no heading. */
  loose: GuideSummary[]
  groups: GuideGroup[]
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

/** The groups that are not a tag, and so have no tag to derive an id from. */
export const GROUP_ANCHORS = { wikis: 'group-wikis' } as const

export function groupGuides(guides: GuideSummary[]): GroupedGuides {
  const byTag = new Map<string, GuideSummary[]>()
  const loose: GuideSummary[] = []

  for (const guide of guides) {
    if (guide.tags.length === 0) {
      loose.push(guide)
      continue
    }
    for (const tag of guide.tags) {
      const members = byTag.get(tag)
      if (members) members.push(guide)
      else byTag.set(tag, [guide])
    }
  }

  /* Alphabetical, because there is no order in the data to respect and an
     arrangement that changes with whichever guide happened to be imported
     first is one a reader cannot learn. */
  const groups = [...byTag.entries()]
    .map(([tag, members]) => ({ tag, guides: members }))
    .sort((a, b) => a.tag.localeCompare(b.tag))

  return { loose, groups }
}

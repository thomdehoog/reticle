/**
 * The Reticle domain model.
 *
 * This file is the single source of truth for the shape of content. The FastAPI
 * backend mirrors these structures exactly, so any change here is a contract
 * change that must land on both sides. Field names are camelCase on the wire;
 * the backend serialises to camelCase rather than the frontend adapting to
 * snake_case, so the UI never has to translate.
 *
 * The shape was checked against ZMB's live corpus of 257 guides rather than
 * guessed. Two findings drove it: navigation runs on tags, not on the category
 * tree, and a category page is a wiki page rather than a bare listing.
 */

export type Role = 'viewer' | 'author' | 'admin'

/**
 * Guides and wiki pages share one lifecycle. Readers only ever resolve a
 * published version; editing happens in place and each publish writes an
 * immutable snapshot, which is what the revision endpoints expose.
 */
export type ContentStatus = 'draft' | 'in_review' | 'published' | 'archived'

export type Difficulty =
  | 'very_easy'
  | 'easy'
  | 'moderate'
  | 'difficult'
  | 'very_difficult'

/**
 * The eight bullet colours and three flags ZMB actually uses, measured across
 * their corpus — every one is in active service, so none can be dropped.
 * All icon artwork in Reticle is original.
 */
export type BulletColor =
  | 'black'
  | 'red'
  | 'orange'
  | 'yellow'
  | 'green'
  | 'light_blue'
  | 'blue'
  | 'violet'

export type BulletIcon = 'note' | 'caution' | 'reminder'

/** Indent depth of a bullet within its step. Levels 0, 1 and 2 are all in use. */
export type BulletLevel = 0 | 1 | 2

export interface Bullet {
  id: string
  text: string
  color: BulletColor
  /** null renders a plain coloured dot; an icon replaces the dot. */
  icon: BulletIcon | null
  level: BulletLevel
}

/**
 * A shape drawn over a step image, in the colour of the bullet it belongs to.
 *
 * Stored as data rather than burned into the picture: the original upload stays
 * intact, the annotation stays editable, and it scales with the responsive
 * image instead of pixellating.
 */
export interface Annotation {
  id: string
  shape: 'rectangle' | 'ellipse' | 'arrow'
  color: BulletColor
  /** Fractions of image width/height in 0..1, so they survive any rendered size. */
  x: number
  y: number
  width: number
  height: number
}

/**
 * A file attached to a step: a still image, or a short clip.
 *
 * Video is one type rather than a parallel one because everything around a
 * picture — upload, ownership, deletion, the reader's media strip — applies
 * identically to a clip of somebody seating a filter cube. Only three fields
 * differ, and they are null on an image rather than absent, so no consumer has
 * to narrow the type before it can read them.
 */
export interface Media {
  id: string
  /** Server-relative path, e.g. /api/media/<id>. Never a data URI once saved. */
  url: string
  kind: 'image' | 'video'
  alt: string
  width: number | null
  height: number | null
  /** Video only. null on an image, and on a clip whose duration is unknown. */
  durationSeconds: number | null
  /** A still frame to show before the clip is fetched; null when there is none. */
  posterUrl: string | null
  annotations: Annotation[]
}

/**
 * A step carries at most four images: three is the common case in ZMB's corpus,
 * and the fourth exists because a handful of instrument steps genuinely use it.
 * The reader shows one large image with the rest as thumbnails beside the text.
 */
export const MAX_MEDIA_PER_STEP = 4

/**
 * What a block inside a guide is.
 *
 * `step` is a numbered instruction. `info` is context that is not one — where
 * the building is, where the reception desk is. `pinned` is the highlighted
 * block at the top, which the API sorts to the front of `steps`.
 *
 * Only `step` is counted when numbering, so an info block between steps 2 and 3
 * does not make the next one 4.
 */
export type StepKind = 'step' | 'info' | 'pinned'

export interface Step {
  id: string
  kind: StepKind
  /** Contiguous from 0 within a guide; the API renumbers on reorder. */
  orderIndex: number
  title: string
  bullets: Bullet[]
  media: Media[]
  /**
   * At most one clip per step, held apart from `media` rather than mixed into
   * it: a step demonstrating a movement needs one video and its stills, and a
   * list that could hold four videos would invite a step nobody can watch.
   */
  video: Media | null
}

export interface UserRef {
  id: string
  displayName: string
}

/**
 * Tags are the navigation. A guide sits in exactly one category but carries
 * many tags, and wiki pages embed tag-filtered guide lists — that is how one
 * instrument guide appears under every heading it is relevant to.
 */
export interface Tag {
  id: string
  slug: string
  name: string
  guideCount: number
}

export interface Guide {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string
  /** Tag slugs. The server creates any tag that does not exist yet. */
  tags: string[]
  /**
   * Offered as a quick link: shown as a wide block on the front page and on
   * every category, above the guides themselves.
   *
   * A handful of procedures answer the question most people arrive with —
   * how to book, how to get in, where the data went — and they are scattered
   * across categories that nobody would think to open. This is the author's
   * way of saying "this one is asked for", rather than a rank the software
   * computes from view counts.
   */
  isQuickLink: boolean
  difficulty: Difficulty
  /**
   * An estimate given as a range, because that is how long a procedure honestly
   * takes. Either end may be null when the author has not estimated it.
   */
  timeRequiredMinMinutes: number | null
  timeRequiredMaxMinutes: number | null
  introduction: string
  conclusion: string
  status: ContentStatus
  steps: Step[]
  author: UserRef
  lastEditedBy: UserRef
  /** Everyone who has edited it, which at a facility is often the real record. */
  contributors: UserRef[]
  viewCount: number
  createdAt: string
  updatedAt: string
  publishedAt: string | null
  /** Increments on each publish, so readers can cite a stable revision. */
  version: number
}

/** Listing projection: everything a card needs, without the step payload. */
export interface GuideSummary {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string
  tags: string[]
  isQuickLink: boolean
  difficulty: Difficulty
  timeRequiredMinMinutes: number | null
  timeRequiredMaxMinutes: number | null
  status: ContentStatus
  stepCount: number
  author: UserRef
  viewCount: number
  /** The guide's first step image: what its card shows. */
  thumbnailUrl: string | null
  updatedAt: string
  publishedAt: string | null
}

/**
 * A wiki page: long-form content written in Markdown, with tag-filtered guide
 * lists embedded in it.
 *
 * A category's landing content is a Page with `isLanding` set, rather than a
 * body field on Category. That way wiki pages, category pages, drafts,
 * publishing and version history are one mechanism instead of two.
 */
export interface Page {
  id: string
  slug: string
  title: string
  summary: string
  /** null for a standalone article that does not belong to a category. */
  categoryId: string | null
  /** True when this page is the landing content for `categoryId`. */
  isLanding: boolean
  /** Markdown. Rendered to React elements, never to raw HTML. */
  body: string
  heroMediaId: string | null
  status: ContentStatus
  author: UserRef
  lastEditedBy: UserRef
  contributors: UserRef[]
  viewCount: number
  createdAt: string
  updatedAt: string
  publishedAt: string | null
  version: number
}

export interface PageSummary {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string | null
  isLanding: boolean
  status: ContentStatus
  heroImageUrl: string | null
  updatedAt: string
  publishedAt: string | null
}

export interface Category {
  id: string
  slug: string
  name: string
  description: string
  /** null for a top-level category; categories nest arbitrarily deep. */
  parentId: string | null
  orderIndex: number
  /**
   * Holding categories exist to own guides that are reached through tags rather
   * than by browsing, and are hidden from the category tree.
   */
  isHidden: boolean
  /** The picture the section is browsed by. */
  heroMediaId: string | null
  imageUrl: string | null
}

export interface User {
  id: string
  email: string
  displayName: string
  role: Role
  isActive: boolean
  createdAt: string
}

/** Search spans both content types, so results say which one they are. */
export type SearchResult =
  | { kind: 'guide'; guide: GuideSummary }
  | { kind: 'page'; page: PageSummary }

/**
 * Who is running this instance.
 *
 * Configuration rather than a constant in the source: Reticle is the software
 * and a facility is a deployment, so another imaging centre runs its own with
 * its own name on it rather than forking this one.
 */
export interface Organisation {
  name: string
  shortName: string
  url: string | null
  /** One line under the name on the front page's banner. */
  tagline: string | null
  /** The photograph behind it. A drawn figure stands in when there is none. */
  heroImageUrl: string | null
}

export interface AppConfig {
  organisation: Organisation
}

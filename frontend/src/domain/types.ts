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
 * Guides and wiki pages share one lifecycle. What the editor saves into is the
 * working copy; each publish writes an immutable snapshot, and that snapshot is
 * what readers are served until the next publish. The revision endpoints
 * expose every snapshot ever written.
 */
export type ContentStatus = 'draft' | 'in_review' | 'published' | 'archived'

/**
 * Which of the two an author is asking for. A viewer is never asked: a viewer
 * gets the published snapshot.
 */
export type ContentView = 'working' | 'published'

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

export interface Media {
  id: string
  /**
   * Videos are stored as uploaded and carry no pixel size or annotations; the
   * kind is what tells a renderer not to treat one as a picture.
   */
  kind: 'image' | 'video'
  /**
   * Server-relative path of the file as it was uploaded, e.g. /api/media/<id>.
   * Never a data URI once saved. This is the one to open at full size.
   */
  url: string
  /**
   * What an `<img>` should load: for an image, a copy held to a size a screen
   * can use, so a forty-megapixel panel is not sent to a phone; for a video the
   * same address as `url`. Snapshots published before the field existed are
   * given it by the server, so it is always there.
   */
  displayUrl: string
  alt: string
  /** The original's pixel size — the right proportions for the display copy too. */
  width: number | null
  height: number | null
  annotations: Annotation[]
}

/** A step carries at most three images; a fourth means it is really two steps. */
export const MAX_MEDIA_PER_STEP = 3

/**
 * Limits the server enforces on every save. Mirrored here so the editor can
 * say what is wrong next to the field, instead of relaying a refused save.
 */
export const MAX_GUIDE_TITLE_LENGTH = 240
export const MAX_TAGS_PER_GUIDE = 30
export const MAX_TAG_LENGTH = 60
export const MAX_ALT_LENGTH = 1000

export interface Step {
  id: string
  /** Contiguous from 0 within a guide; the API renumbers on reorder. */
  orderIndex: number
  title: string
  bullets: Bullet[]
  media: Media[]
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
  /**
   * True when this is published and its working copy no longer reads the same
   * as the version readers have. Only ever true for an author: to a viewer the
   * server always says false, because that newer work exists is not theirs to
   * know.
   */
  hasUnpublishedChanges: boolean
}

/** Listing projection: everything a card needs, without the step payload. */
export interface GuideSummary {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string
  tags: string[]
  difficulty: Difficulty
  timeRequiredMinMinutes: number | null
  timeRequiredMaxMinutes: number | null
  status: ContentStatus
  stepCount: number
  author: UserRef
  viewCount: number
  updatedAt: string
  publishedAt: string | null
  hasUnpublishedChanges: boolean
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
  /**
   * What the hero shows, for someone who cannot see it. Belongs to the page,
   * not the upload; the server keeps it only while there is a hero. A snapshot
   * published before the field existed does not carry it at all, which is why
   * the reader falls back to the empty string.
   */
  heroAlt: string
  status: ContentStatus
  author: UserRef
  lastEditedBy: UserRef
  contributors: UserRef[]
  viewCount: number
  createdAt: string
  updatedAt: string
  publishedAt: string | null
  version: number
  /** See `Guide.hasUnpublishedChanges`. */
  hasUnpublishedChanges: boolean
}

export interface PageSummary {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string | null
  isLanding: boolean
  status: ContentStatus
  updatedAt: string
  publishedAt: string | null
  hasUnpublishedChanges: boolean
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

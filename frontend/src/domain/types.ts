/**
 * The Reticle domain model.
 *
 * This file is the single source of truth for the shape of a guide. The
 * FastAPI backend mirrors these structures exactly, so any change here is a
 * contract change that must land on both sides. Field names are camelCase on
 * the wire; the backend serialises to camelCase rather than the frontend
 * adapting to snake_case, so the UI never has to translate.
 */

export type Role = 'viewer' | 'author' | 'admin'

/**
 * Guides move draft -> in_review -> published. Readers only ever resolve a
 * published revision; authors editing a published guide work on a draft
 * revision so the live version never breaks mid-edit.
 */
export type GuideStatus = 'draft' | 'in_review' | 'published' | 'archived'

export type Difficulty =
  | 'very_easy'
  | 'easy'
  | 'moderate'
  | 'difficult'
  | 'very_difficult'

/**
 * Bullet colours and icons cover the annotation vocabulary technical procedures
 * need: a neutral default, severity colours, and flags for notes, cautions and
 * reminders. Keeping this set stable means imported guides retain the emphasis
 * their authors intended. All icon artwork in Reticle is original.
 */
export type BulletColor =
  | 'black'
  | 'red'
  | 'orange'
  | 'yellow'
  | 'green'
  | 'blue'
  | 'violet'

export type BulletIcon = 'note' | 'caution' | 'warning' | 'reminder'

/** Indent depth of a bullet within its step. Dozuki allows two sub-levels. */
export type BulletLevel = 0 | 1 | 2

export interface Bullet {
  id: string
  text: string
  color: BulletColor
  /** null renders a plain coloured dot; an icon replaces the dot. */
  icon: BulletIcon | null
  level: BulletLevel
}

export interface Media {
  id: string
  /** Server-relative path, e.g. /api/media/<id>. Never a data URI once saved. */
  url: string
  alt: string
  width: number | null
  height: number | null
}

/**
 * A step carries at most three images. The cap is a deliberate editorial
 * constraint: a step that needs a fourth picture is really two steps.
 */
export const MAX_MEDIA_PER_STEP = 3

export interface Step {
  id: string
  /** Contiguous from 0 within a guide; the API renumbers on reorder. */
  orderIndex: number
  title: string
  bullets: Bullet[]
  media: Media[]
}

export interface CategoryRef {
  id: string
  slug: string
  name: string
}

export interface UserRef {
  id: string
  displayName: string
}

export interface Guide {
  id: string
  slug: string
  title: string
  summary: string
  categoryId: string
  difficulty: Difficulty
  /** Whole minutes; null when the author has not estimated it. */
  timeRequiredMinutes: number | null
  introduction: string
  conclusion: string
  status: GuideStatus
  steps: Step[]
  /** Guides whose steps are prepended when this one is read start-to-finish. */
  prerequisiteIds: string[]
  author: UserRef
  lastEditedBy: UserRef
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
  difficulty: Difficulty
  timeRequiredMinutes: number | null
  status: GuideStatus
  stepCount: number
  author: UserRef
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
}

export interface User {
  id: string
  email: string
  displayName: string
  role: Role
  createdAt: string
}

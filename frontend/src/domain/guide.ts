/**
 * Pure guide logic, deliberately free of React and of the network.
 *
 * The editor is the riskiest part of Reticle — reordering steps, moving
 * bullets, enforcing limits — so that logic lives here as plain functions that
 * can be tested directly, instead of being buried in component event handlers
 * where it can only be reached through a rendered DOM.
 */

import { ulid } from 'ulid'

import {
  type Bullet,
  type BulletLevel,
  type Difficulty,
  type Guide,
  MAX_MEDIA_PER_STEP,
  type Step,
} from './types'

/**
 * Identifiers for rows the author has just created.
 *
 * These are real ULIDs, not placeholders. The server validates every
 * client-supplied id and accepts an unknown one precisely so an optimistically
 * created row keeps the key it was given — so minting a proper ULID here means
 * a step keeps one identity from the moment it appears on screen, through
 * every autosave, to the database. A placeholder scheme would be rejected
 * outright, and autosave would fail silently from the first added step onward.
 *
 * `ulid()` also avoids `crypto.randomUUID`, which is unavailable outside a
 * secure context — exactly what a ZMB intranet deployment over plain http is.
 */
export function newId(): string {
  return ulid()
}

export function createBullet(overrides: Partial<Bullet> = {}): Bullet {
  return {
    id: newId(),
    text: '',
    color: 'black',
    icon: null,
    level: 0,
    ...overrides,
  }
}

export function createStep(overrides: Partial<Step> = {}): Step {
  return {
    id: newId(),
    orderIndex: 0,
    title: '',
    bullets: [createBullet()],
    media: [],
    ...overrides,
  }
}

/**
 * Rewrites `orderIndex` to match array position. Every mutation that changes
 * step order funnels through here so array position stays the single source of
 * truth and the two can never disagree.
 */
export function renumberSteps(steps: Step[]): Step[] {
  return steps.map((step, index) =>
    step.orderIndex === index ? step : { ...step, orderIndex: index },
  )
}

/** Moves a step, returning a renumbered array. Out-of-range input is returned unchanged. */
export function moveStep(steps: Step[], from: number, to: number): Step[] {
  if (from === to) return steps
  if (from < 0 || from >= steps.length) return steps
  if (to < 0 || to >= steps.length) return steps

  const reordered = [...steps]
  const [moved] = reordered.splice(from, 1)
  reordered.splice(to, 0, moved)
  return renumberSteps(reordered)
}

export function insertStepAfter(steps: Step[], index: number): Step[] {
  const at = Math.min(Math.max(index + 1, 0), steps.length)
  const reordered = [...steps]
  reordered.splice(at, 0, createStep())
  return renumberSteps(reordered)
}

/** Removing the final step is refused: a guide with zero steps is not a guide. */
export function removeStep(steps: Step[], index: number): Step[] {
  if (steps.length <= 1) return steps
  if (index < 0 || index >= steps.length) return steps
  return renumberSteps(steps.filter((_, i) => i !== index))
}

export function canAcceptMedia(step: Step): boolean {
  return step.media.length < MAX_MEDIA_PER_STEP
}

/** Indent is clamped rather than rejected, so holding Tab cannot corrupt a bullet. */
export function indentBullet(bullet: Bullet, delta: number): Bullet {
  const level = Math.min(Math.max(bullet.level + delta, 0), 2) as BulletLevel
  return level === bullet.level ? bullet : { ...bullet, level }
}

export const DIFFICULTY_LABELS: Record<Difficulty, string> = {
  very_easy: 'Very easy',
  easy: 'Easy',
  moderate: 'Moderate',
  difficult: 'Difficult',
  very_difficult: 'Very difficult',
}

export const DIFFICULTY_ORDER: Difficulty[] = [
  'very_easy',
  'easy',
  'moderate',
  'difficult',
  'very_difficult',
]

/** Renders a duration the way a person would say it: "1 h 30 min", not "90 min". */
export function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes} min`

  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return remainder === 0 ? `${hours} h` : `${hours} h ${remainder} min`
}

/**
 * Estimates are a range because that is how long a procedure honestly takes —
 * a confocal session is "30 minutes to an hour and a half" depending on how the
 * sample behaves, and a single number would be a lie in one direction.
 */
export function formatDurationRange(
  minMinutes: number | null,
  maxMinutes: number | null,
): string {
  const low = minMinutes !== null && minMinutes > 0 ? minMinutes : null
  const high = maxMinutes !== null && maxMinutes > 0 ? maxMinutes : null

  if (low === null && high === null) return 'Not specified'
  if (low === null) return `up to ${formatMinutes(high as number)}`
  if (high === null || high === low) return formatMinutes(low)
  if (high < low) return `${formatMinutes(high)} – ${formatMinutes(low)}`
  return `${formatMinutes(low)} – ${formatMinutes(high)}`
}

export interface ValidationIssue {
  field: string
  message: string
}

/**
 * Publish-time validation. Drafts are intentionally allowed to be incomplete —
 * an author must be able to save a half-written guide and come back tomorrow —
 * so these rules are applied when publishing, not when saving.
 */
export function validateForPublish(guide: Guide): ValidationIssue[] {
  const issues: ValidationIssue[] = []

  if (guide.title.trim() === '') {
    issues.push({ field: 'title', message: 'A guide needs a title before it can be published.' })
  }
  if (guide.categoryId.trim() === '') {
    issues.push({ field: 'categoryId', message: 'Choose a category so people can find this guide.' })
  }
  if (guide.steps.length === 0) {
    issues.push({ field: 'steps', message: 'A guide needs at least one step.' })
  }

  guide.steps.forEach((step, index) => {
    const hasText = step.bullets.some((bullet) => bullet.text.trim() !== '')
    if (!hasText && step.media.length === 0) {
      issues.push({
        field: `steps.${index}`,
        message: `Step ${index + 1} is empty — add an instruction or an image, or remove it.`,
      })
    }
    if (step.media.length > MAX_MEDIA_PER_STEP) {
      issues.push({
        field: `steps.${index}.media`,
        message: `Step ${index + 1} has ${step.media.length} images; the maximum is ${MAX_MEDIA_PER_STEP}.`,
      })
    }
  })

  return issues
}

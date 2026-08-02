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
  type BulletColor,
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
    kind: 'step',
    orderIndex: 0,
    title: '',
    bullets: [createBullet()],
    media: [],
    video: null,
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

/**
 * The number a reader sees against each block, keyed by block id.
 *
 * Only `step` blocks are counted, so an info block sitting between steps 2 and
 * 3 does not make the next one 4. Blocks that are not numbered are absent from
 * the map rather than mapped to null, so a caller that forgets to handle them
 * gets `undefined` and shows nothing, rather than showing a zero.
 *
 * It lives here rather than in the reader because the editor has to agree with
 * it exactly: an author writing step 7 must be looking at what a reader will
 * call step 7.
 */
export function numberedSteps(steps: Step[]): Map<string, number> {
  const numbers = new Map<string, number>()
  let counted = 0
  for (const step of steps) {
    if (step.kind !== 'step') continue
    counted += 1
    numbers.set(step.id, counted)
  }
  return numbers
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

/** How deep a bullet may be indented. Levels 0, 1 and 2 are all in ZMB's corpus. */
export const MAX_BULLET_LEVEL = 2

/** Indent is clamped rather than rejected, so holding Tab cannot corrupt a bullet. */
export function indentBullet(bullet: Bullet, delta: number): Bullet {
  const level = Math.min(Math.max(bullet.level + delta, 0), MAX_BULLET_LEVEL) as BulletLevel
  return level === bullet.level ? bullet : { ...bullet, level }
}

/**
 * Which number each shape colour carries within a step.
 *
 * A bullet is tied to a shape on the picture by colour and nothing else, and
 * colour is a channel some readers do not have: orange and yellow here are one
 * colour under deuteranopia, every colour is one colour on the greyscale
 * photocopy taped to an instrument, and a screen reader is told nothing at all.
 * So each shape is numbered and the bullets it belongs to carry the same
 * number, and the pairing survives without it.
 *
 * A colour keeps one number however many shapes are drawn in it — two red
 * rectangles are both "1", because both are what the red bullet is pointing at.
 * Numbering runs over the step's images in the order a reader meets them. The
 * video slot is skipped: there is no way to draw on a clip.
 */
export function numberShapeColors(step: Step): Partial<Record<BulletColor, number>> {
  const numbers: Partial<Record<BulletColor, number>> = {}

  for (const image of step.media) {
    for (const annotation of image.annotations) {
      if (numbers[annotation.color] === undefined) {
        numbers[annotation.color] = Object.keys(numbers).length + 1
      }
    }
  }

  return numbers
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

/** The server's ceilings, mirrored so the editor can name the offending field. */
export const MAX_TITLE_LENGTH = 240
export const MAX_TAGS_PER_GUIDE = 40

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

  /**
   * The limits below are the server's, mirrored here so that publishing can
   * point at the field that is wrong. Left to the server they surface as one
   * page-level red sentence produced by the save that publishing performs
   * first — which tells an author that something is too long without telling
   * them what.
   */
  if (guide.title.length > MAX_TITLE_LENGTH) {
    issues.push({
      field: 'title',
      message: `A title can be at most ${MAX_TITLE_LENGTH} characters; this one is ${guide.title.length}.`,
    })
  }
  if (guide.tags.length > MAX_TAGS_PER_GUIDE) {
    issues.push({
      field: 'tags',
      message: `A guide can carry at most ${MAX_TAGS_PER_GUIDE} tags; this one has ${guide.tags.length}.`,
    })
  }
  if (
    guide.timeRequiredMinMinutes !== null &&
    guide.timeRequiredMaxMinutes !== null &&
    guide.timeRequiredMinMinutes > guide.timeRequiredMaxMinutes
  ) {
    issues.push({
      field: 'timeRequiredMinMinutes',
      message: 'The shortest time cannot be longer than the longest time.',
    })
  }
  if (guide.categoryId.trim() === '') {
    issues.push({ field: 'categoryId', message: 'Choose a category so people can find this guide.' })
  }
  if (guide.steps.length === 0) {
    issues.push({ field: 'steps', message: 'A guide needs at least one step.' })
  }

  guide.steps.forEach((step, index) => {
    const hasText = step.bullets.some((bullet) => bullet.text.trim() !== '')
    /* A step that is nothing but a clip of the movement is a real step: several
       ZMB procedures say "do it like this" and show it, with no text at all. */
    if (!hasText && step.media.length === 0 && step.video === null) {
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

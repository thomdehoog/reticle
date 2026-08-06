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
  type Media,
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

/**
 * Moves one of a step's pictures one place earlier or later.
 *
 * Order is not cosmetic: the first picture is the large one a reader sees and
 * the rest are its thumbnails, so this is how an author chooses which picture
 * leads. A move that would fall off either end returns the array unchanged
 * rather than wrapping around, because wrapping would make the last picture
 * become the first on a click that looked like a nudge.
 */
export function moveMedia(media: Media[], mediaId: string, delta: -1 | 1): Media[] {
  const from = media.findIndex((image) => image.id === mediaId)
  if (from === -1) return media
  const to = from + delta
  if (to < 0 || to >= media.length) return media

  const moved = [...media]
  const [image] = moved.splice(from, 1)
  moved.splice(to, 0, image)
  return moved
}

/**
 * Makes one of a step's pictures the first — the large one a reader sees.
 *
 * This is the whole of reordering as far as an author is concerned. Promoting
 * pictures one at a time reaches any arrangement, and it is one click on the
 * picture itself rather than two arrow buttons on each of four thumbnails, in
 * a strip too narrow to hold them. The others keep their order behind it.
 *
 * A picture that is already first, or is not in this step, returns the array
 * unchanged, so a caller never has to check first.
 */
export function promoteMedia(media: Media[], mediaId: string): Media[] {
  const from = media.findIndex((image) => image.id === mediaId)
  if (from <= 0) return media
  const moved = [...media]
  const [image] = moved.splice(from, 1)
  moved.unshift(image)
  return moved
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
 * Drawn on the picture, beside the shape. It once had a partner in the text —
 * every bullet of that colour showed the same digit — which is the form the
 * pairing took when it had to survive a greyscale print and a screen reader.
 * The bullets carry a colour and nothing else now, so this numbers the picture
 * alone: it tells a reader that the two red rectangles over there are one mark
 * and the yellow arrow is another, which is worth saying on a screenshot busy
 * enough to need three.
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
/** The server stores minutes as a whole number in 0..100000 and refuses the rest. */
export const MAX_TIME_REQUIRED_MINUTES = 100_000

/**
 * What a "time required" box is allowed to put into the guide.
 *
 * A number field hands back whatever was typed, so `1.5`, `-5` and
 * `999999999` all arrive here as numbers the server will not store. It refuses
 * the *whole document* when one of them does, which is the damage: the save
 * that carries a stray decimal point also carries the three paragraphs written
 * after it, and the author is told only "timeRequiredMinMinutes: Input should
 * be a valid integer" — a field name that appears nowhere on their screen.
 * Rounding and clamping here keeps the model inside what the server accepts, so
 * a typo costs the typo and nothing else.
 */
export function cleanTimeRequired(raw: string): number | null {
  if (raw.trim() === '') return null
  const value = Number(raw)
  if (!Number.isFinite(value)) return null
  return Math.min(Math.max(Math.round(value), 0), MAX_TIME_REQUIRED_MINUTES)
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

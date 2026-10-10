/**
 * What may be uploaded, decided before a byte is sent.
 *
 * The server has the last word — it identifies a file from its contents, not
 * from anything the browser says about it. These checks exist so that the
 * common mistakes are answered at once: a 400 MB screen recording should be
 * refused when it is dropped, not after ten minutes of uploading it.
 */

import { MAX_MEDIA_PER_STEP } from './types'

/**
 * The server's defaults, from docs/API.md. All three are the operator's to
 * change, so these are not the limits: they are what the editor assumes for
 * the moment before `GET /api/config` has answered, and what it falls back to
 * against a server too old to have that endpoint.
 */
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024

/** What this server accepts, as `GET /api/config` reports it. */
export interface UploadLimits {
  maxImageBytes: number
  maxVideoBytes: number
  maxMediaPerStep: number
}

export const DEFAULT_UPLOAD_LIMITS: UploadLimits = {
  maxImageBytes: MAX_IMAGE_BYTES,
  maxVideoBytes: MAX_VIDEO_BYTES,
  maxMediaPerStep: MAX_MEDIA_PER_STEP,
}

/**
 * The server's answer, with a default wherever it is not a usable number.
 *
 * These figures gate what the editor will even try to send, so a malformed
 * answer must not become a limit: `undefined` here would turn every size
 * comparison false and wave a 4 GB file through, and a zero would refuse
 * everything in the server's name.
 */
export function uploadLimitsFrom(answer: unknown): UploadLimits {
  const given = (answer ?? {}) as Partial<Record<keyof UploadLimits, unknown>>
  const limits = { ...DEFAULT_UPLOAD_LIMITS }
  for (const key of Object.keys(limits) as (keyof UploadLimits)[]) {
    const value = given[key]
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) limits[key] = value
  }
  return limits
}

/**
 * The longest side of the copy of an image the server hands out for display
 * (`Media.displayUrl`). A picture no larger than this has no separate copy —
 * what is shown *is* the original — so there is nothing more to offer.
 */
export const DISPLAY_MAX_SIDE = 2560

/** Whether the original is larger than what the reader is being shown. */
export function hasLargerOriginal(media: { width: number | null; height: number | null }): boolean {
  return Math.max(media.width ?? 0, media.height ?? 0) > DISPLAY_MAX_SIDE
}

const BARE_MEDIA_URL = /^\/api\/media\/[0-9A-Za-z]+$/

/**
 * The address to load for a picture written into a wiki page.
 *
 * A page body names an upload by its plain address, `/api/media/<id>`, because
 * that is what the editor inserts and what pages written before display copies
 * existed contain. Shown as it stands, that is the full original. An address
 * that already says which size it wants, and any address that is not one of
 * ours, is left exactly as the author wrote it.
 */
export function displayUrlFor(src: string): string {
  return BARE_MEDIA_URL.test(src) ? `${src}?size=display` : src
}

const IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif']
const VIDEO_TYPES = ['video/mp4', 'video/webm']

/** For a file input's `accept`, so the picker offers only what will be taken. */
export const STEP_MEDIA_ACCEPT = [...IMAGE_TYPES, ...VIDEO_TYPES].join(',')
export const IMAGE_ACCEPT = IMAGE_TYPES.join(',')

const EXTENSION_KINDS: Record<string, 'image' | 'video'> = {
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  webp: 'image',
  gif: 'image',
  mp4: 'video',
  m4v: 'video',
  webm: 'video',
}

/**
 * Image, video, or neither. The declared type is used when there is one; some
 * systems hand over a file with none at all — a `.webm` straight off a
 * microscope PC is typical — and then the extension has to do.
 */
export function mediaKindOf(file: Pick<File, 'name' | 'type'>): 'image' | 'video' | null {
  if (IMAGE_TYPES.includes(file.type)) return 'image'
  if (VIDEO_TYPES.includes(file.type)) return 'video'
  if (file.type !== '') return null

  const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
  return EXTENSION_KINDS[extension] ?? null
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} kB`
  const megabytes = bytes / (1024 * 1024)
  return `${megabytes >= 100 ? Math.round(megabytes) : megabytes.toFixed(1)} MB`
}

/**
 * Why a file cannot go into a step, in words for the person who dropped it —
 * or null when there is no reason to refuse it here. `limits` are the server's
 * own (see `useUploadLimits`); the defaults stand in until they are known.
 */
export function stepMediaProblem(
  file: Pick<File, 'name' | 'type' | 'size'>,
  limits: UploadLimits = DEFAULT_UPLOAD_LIMITS,
): string | null {
  const kind = mediaKindOf(file)
  if (kind === null) {
    return `“${file.name}” is not a picture or a video Reticle can show. Use PNG, JPEG, WebP or GIF for images, and MP4 or WebM for video.`
  }
  const limit = kind === 'image' ? limits.maxImageBytes : limits.maxVideoBytes
  if (file.size > limit) {
    return `“${file.name}” is ${formatBytes(file.size)}; ${kind === 'image' ? 'an image' : 'a video'} can be at most ${formatBytes(limit)}.`
  }
  return null
}

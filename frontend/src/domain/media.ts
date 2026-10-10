/**
 * What may be uploaded, decided before a byte is sent.
 *
 * The server has the last word — it identifies a file from its contents, not
 * from anything the browser says about it. These checks exist so that the
 * common mistakes are answered at once: a 400 MB screen recording should be
 * refused when it is dropped, not after ten minutes of uploading it.
 */

/** The limits in docs/API.md. The video one is configurable on the server. */
export const MAX_IMAGE_BYTES = 20 * 1024 * 1024
export const MAX_VIDEO_BYTES = 200 * 1024 * 1024

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
 * or null when there is no reason to refuse it here.
 */
export function stepMediaProblem(file: Pick<File, 'name' | 'type' | 'size'>): string | null {
  const kind = mediaKindOf(file)
  if (kind === null) {
    return `“${file.name}” is not a picture or a video Reticle can show. Use PNG, JPEG, WebP or GIF for images, and MP4 or WebM for video.`
  }
  const limit = kind === 'image' ? MAX_IMAGE_BYTES : MAX_VIDEO_BYTES
  if (file.size > limit) {
    return `“${file.name}” is ${formatBytes(file.size)}; ${kind === 'image' ? 'an image' : 'a video'} can be at most ${formatBytes(limit)}.`
  }
  return null
}

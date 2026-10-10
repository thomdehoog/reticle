import { describe, expect, it } from 'vitest'

import {
  DEFAULT_UPLOAD_LIMITS,
  MAX_IMAGE_BYTES,
  MAX_VIDEO_BYTES,
  formatBytes,
  mediaKindOf,
  stepMediaProblem,
  uploadLimitsFrom,
} from './media'

const file = (name: string, type: string, size = 1000) => ({ name, type, size })

describe('mediaKindOf', () => {
  it.each([
    ['shot.png', 'image/png', 'image'],
    ['shot.jpg', 'image/jpeg', 'image'],
    ['shot.webp', 'image/webp', 'image'],
    ['anim.gif', 'image/gif', 'image'],
    ['clip.mp4', 'video/mp4', 'video'],
    ['clip.webm', 'video/webm', 'video'],
  ])('recognises %s', (name, type, kind) => {
    expect(mediaKindOf(file(name, type))).toBe(kind)
  })

  it.each([
    ['clip.mov', 'video/quicktime'],
    ['clip.avi', 'video/x-msvideo'],
    ['figure.tiff', 'image/tiff'],
    ['figure.svg', 'image/svg+xml'],
    ['notes.pdf', 'application/pdf'],
  ])('refuses %s, which the server would refuse too', (name, type) => {
    expect(mediaKindOf(file(name, type))).toBeNull()
  })

  it('falls back on the extension when the system declares no type', () => {
    expect(mediaKindOf(file('Tile Scan.WEBM', ''))).toBe('video')
    expect(mediaKindOf(file('stage.JPG', ''))).toBe('image')
    expect(mediaKindOf(file('README', ''))).toBeNull()
  })

  it('does not let an extension overrule a declared type', () => {
    expect(mediaKindOf(file('really-a-pdf.png', 'application/pdf'))).toBeNull()
  })
})

describe('stepMediaProblem', () => {
  it('has nothing to say about a file that fits', () => {
    expect(stepMediaProblem(file('a.png', 'image/png', MAX_IMAGE_BYTES))).toBeNull()
    expect(stepMediaProblem(file('a.mp4', 'video/mp4', MAX_VIDEO_BYTES))).toBeNull()
  })

  it('names the file and the formats when the kind is wrong', () => {
    const problem = stepMediaProblem(file('recording.avi', 'video/x-msvideo'))
    expect(problem).toContain('“recording.avi”')
    expect(problem).toContain('MP4 or WebM')
  })

  it('gives the size and the limit when an image is too large', () => {
    expect(stepMediaProblem(file('stitch.png', 'image/png', MAX_IMAGE_BYTES + 1))).toBe(
      '“stitch.png” is 20.0 MB; an image can be at most 20.0 MB.',
    )
  })

  it('holds a video to the video limit, not the image one', () => {
    expect(stepMediaProblem(file('run.mp4', 'video/mp4', 150 * 1024 * 1024))).toBeNull()
    expect(stepMediaProblem(file('run.mp4', 'video/mp4', 350 * 1024 * 1024))).toBe(
      '“run.mp4” is 350 MB; a video can be at most 200 MB.',
    )
  })
})

describe('formatBytes', () => {
  it('uses the unit a person would', () => {
    expect(formatBytes(200)).toBe('1 kB')
    expect(formatBytes(340 * 1024)).toBe('340 kB')
    expect(formatBytes(5.25 * 1024 * 1024)).toBe('5.3 MB')
    expect(formatBytes(200 * 1024 * 1024)).toBe('200 MB')
  })
})

describe('stepMediaProblem — with the server\'s own limits', () => {
  const MB = 1024 * 1024

  it('accepts what a more generous server accepts', () => {
    const limits = { ...DEFAULT_UPLOAD_LIMITS, maxVideoBytes: 500 * MB }

    expect(stepMediaProblem(file('run.mp4', 'video/mp4', 350 * MB), limits)).toBeNull()
  })

  it('refuses, with the real figure, what a stricter server refuses', () => {
    const limits = { ...DEFAULT_UPLOAD_LIMITS, maxImageBytes: 5 * MB }

    expect(stepMediaProblem(file('stitch.png', 'image/png', 8 * MB), limits)).toBe(
      '“stitch.png” is 8.0 MB; an image can be at most 5.0 MB.',
    )
  })
})

describe('uploadLimitsFrom', () => {
  it('takes the server at its word', () => {
    expect(uploadLimitsFrom({ maxImageBytes: 1, maxVideoBytes: 2, maxMediaPerStep: 5 })).toEqual({
      maxImageBytes: 1,
      maxVideoBytes: 2,
      maxMediaPerStep: 5,
    })
  })

  it('ignores anything else the answer carries', () => {
    expect(uploadLimitsFrom({ ...DEFAULT_UPLOAD_LIMITS, secretKey: 'x' })).toEqual(
      DEFAULT_UPLOAD_LIMITS,
    )
  })

  /* A limit that is not a number would make every "is it too big" comparison
     false, and the editor would start a 4 GB upload the server will refuse. */
  it.each([null, undefined, 'nonsense', [], { id: 'u1', role: 'admin' }])(
    'falls back to the defaults for %j',
    (answer) => {
      expect(uploadLimitsFrom(answer)).toEqual(DEFAULT_UPLOAD_LIMITS)
    },
  )

  it('replaces only the figures that are unusable', () => {
    expect(
      uploadLimitsFrom({ maxImageBytes: 0, maxVideoBytes: '200', maxMediaPerStep: 4 }),
    ).toEqual({ ...DEFAULT_UPLOAD_LIMITS, maxMediaPerStep: 4 })
    expect(uploadLimitsFrom({ maxImageBytes: Number.NaN, maxVideoBytes: -1 })).toEqual(
      DEFAULT_UPLOAD_LIMITS,
    )
  })
})

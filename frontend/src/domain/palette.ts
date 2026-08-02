/**
 * The eight-colour palette, in one place.
 *
 * The pairing is the feature: a red rectangle drawn on a screenshot means "the
 * red bullet beside it". That only holds while the shape and the marker are the
 * same red, and two declarations of one fact drift — invisibly, until somebody
 * at an instrument follows the wrong arrow.
 *
 * These values are the SVG overlay's copy. The stylesheet keeps its own as
 * `--shape-*`, because CSS cannot import from here; `palette.test.ts` reads
 * app.css and fails if the two disagree. `--bullet-*` is a different thing and
 * is allowed to differ: it is the colour of a bullet's *words*, which lighten
 * on a dark page, while a shape drawn on a photograph cannot.
 */

import type { BulletColor, BulletIcon } from './types'

export const BULLET_COLOR_HEX: Record<BulletColor, string> = {
  black: '#1f2328',
  red: '#d1242f',
  orange: '#bc4c00',
  yellow: '#9a6700',
  green: '#1a7f37',
  light_blue: '#0e7490',
  blue: '#0969da',
  violet: '#8250df',
}

/** The order the colour pickers offer, black first because it is the default. */
export const BULLET_COLOR_ORDER: BulletColor[] = [
  'black',
  'red',
  'orange',
  'yellow',
  'green',
  'light_blue',
  'blue',
  'violet',
]

/**
 * The word each flag is spelled out as, in the reader and in the editor alike.
 *
 * One list rather than one per screen: an icon on its own is not a distinction —
 * it vanishes for a colour-blind reader, in a greyscale photocopy taped to an
 * instrument, and at arm's length — so the word carries the meaning, and a
 * caution that is spelled differently in the editor than in the guide is a
 * caution somebody stops trusting.
 */
export const BULLET_FLAG_LABELS: Record<BulletIcon, string> = {
  note: 'Note',
  caution: 'Caution',
  reminder: 'Reminder',
}

/** The custom property holding this colour's text tone, e.g. `--bullet-light-blue`. */
export function bulletColorProperty(color: BulletColor): string {
  return `--bullet-${color.replace(/_/g, '-')}`
}

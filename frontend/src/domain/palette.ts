/**
 * The eight-colour palette, in one place.
 *
 * The pairing is the feature: a red rectangle drawn on a screenshot means "the
 * red bullet beside it". That only holds if the shape and the dot are the same
 * red, and they were previously declared twice — once as CSS custom properties
 * for the bullets and once as a JavaScript record for the SVG overlay. Two
 * declarations of one fact drift, and the drift is invisible until somebody at
 * an instrument follows the wrong arrow.
 *
 * The stylesheet still owns `--bullet-*` because CSS cannot import from here;
 * `palette.test.ts` reads app.css and fails if the two disagree.
 */

import type { BulletColor } from './types'

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

/** The custom property holding this colour, e.g. `--bullet-light-blue`. */
export function bulletColorProperty(color: BulletColor): string {
  return `--bullet-${color.replace(/_/g, '-')}`
}

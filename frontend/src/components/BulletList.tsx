/**
 * The coloured points written beside a step's picture.
 *
 * A step in a guide is a picture on the left and a short list of points on the
 * right. Each point has a colour, and that colour is not decoration: a red point
 * matches the red shape drawn on the picture, so "the switch marked in red" needs
 * no further explanation. Some points also carry a flag - Note, Caution or
 * Reminder - and points can be indented under one another.
 *
 * This file draws that list. It is separate from the editor that writes it,
 * because a reader must see exactly what an author wrote, and the safest way to
 * guarantee that is for both to use this same component.
 */

import type { ComponentType } from 'react'

import { BULLET_FLAG_LABELS } from '../domain/palette'
import type { Bullet, BulletIcon, Step } from '../domain/types'
import { RichInline } from './RichText'
import { IconCaution, IconNote, IconReminder } from './icons'

const ICON_COMPONENTS: Record<BulletIcon, ComponentType<{ size?: number }>> = {
  note: IconNote,
  caution: IconCaution,
  reminder: IconReminder,
}

/**
 * Renders one bullet's marker and text.
 *
 * Two rules hold this together, and both exist for safety rather than looks.
 *
 * First, a flag's treatment is driven by its *kind*, not by the colour the
 * author happened to pick. Colour and kind are independent axes in the model,
 * so nothing guarantees a caution is red — and a caution that reads like a note
 * is the failure mode that matters in a building with lasers and cryogens.
 *
 * Second, the kind is spelled out in words. An icon alone is not a distinction:
 * it disappears for a colour-blind reader, in a greyscale photocopy taped to an
 * instrument, and at arm's length on a phone. "CAUTION" survives all three.
 *
 * Bullet text goes through `RichInline`: bold, italic and links, and nothing
 * else. Markdown is rendered to React elements rather than to an HTML string,
 * so raw HTML in a bullet is ignored rather than escaped-and-hopefully-caught.
 * Guide content is written by staff but read by everyone, and treating it as
 * markup would otherwise turn the editor into a stored-XSS vector.
 *
 * A bullet's marker is its flag icon, or a dot in its colour — never a number.
 * It showed the number of its own shape colour for a while, so that the tie
 * between a bullet and the shape it talks about survived a greyscale print and
 * a screen reader. The owner's call is that a digit in the left margin of the
 * text is clutter, and that a bullet carries a colour and nothing else. The
 * shapes keep their numbers: on the picture a number is an annotation like any
 * other, and it is read there rather than in the running text.
 */
function BulletItem({ bullet }: { bullet: Bullet }) {
  const Icon = bullet.icon ? ICON_COMPONENTS[bullet.icon] : null

  return (
    <li
      className={[
        'bullet',
        `bullet--color-${bullet.color}`,
        `bullet--level-${bullet.level}`,
        bullet.icon ? 'bullet--flagged' : '',
        bullet.icon ? `bullet--kind-${bullet.icon}` : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span className="bullet__marker">
        {Icon ? <Icon size={17} /> : <span className="bullet__dot" />}
      </span>
      <span className="bullet__text">
        {bullet.icon && <span className="bullet__flag-label">{BULLET_FLAG_LABELS[bullet.icon]}</span>}
        <RichInline text={bullet.text} />
      </span>
    </li>
  )
}

/** Takes the whole step rather than its bullets, so a caller has one thing to pass. */
export function BulletList({ step }: { step: Step }) {
  const visible = step.bullets.filter((bullet) => bullet.text.trim() !== '')
  if (visible.length === 0) return null

  return (
    <ul className="bullets">
      {visible.map((bullet) => (
        <BulletItem key={bullet.id} bullet={bullet} />
      ))}
    </ul>
  )
}

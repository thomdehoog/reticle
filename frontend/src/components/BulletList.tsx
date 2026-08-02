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

import { numberShapeColors } from '../domain/guide'
import type { Bullet, BulletIcon, Step } from '../domain/types'
import { IconCaution, IconNote, IconReminder } from './icons'

const ICON_COMPONENTS: Record<BulletIcon, ComponentType<{ size?: number }>> = {
  note: IconNote,
  caution: IconCaution,
  reminder: IconReminder,
}

const ICON_LABELS: Record<BulletIcon, string> = {
  note: 'Note',
  caution: 'Caution',
  reminder: 'Reminder',
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
 * Bullet text is rendered as plain text, never as HTML. Guide content is
 * written by staff but read by everyone, and treating it as markup would turn
 * the editor into a stored-XSS vector for no editorial benefit.
 *
 * A bullet whose colour is drawn somewhere on the step's pictures shows that
 * shape's number instead of a dot or a flag icon. Nothing is lost by replacing
 * the icon: the flag says "CAUTION" in words beside the text, which is what a
 * reader was relying on anyway.
 */
function BulletItem({ bullet, shapeNumber }: { bullet: Bullet; shapeNumber?: number }) {
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
        {shapeNumber === undefined ? (
          Icon ? (
            <Icon size={17} />
          ) : (
            <span className="bullet__dot" />
          )
        ) : (
          <>
            <span className="bullet__number" aria-hidden="true">
              {shapeNumber}
            </span>
            {/* The overlay itself is hidden from assistive technology - it is a
                picture, not a document - so this is the only place a screen
                reader can be told which shape the instruction is about. */}
            <span className="visually-hidden">Marked {shapeNumber} on the picture: </span>
          </>
        )}
      </span>
      <span className="bullet__text">
        {bullet.icon && <span className="bullet__flag-label">{ICON_LABELS[bullet.icon]}</span>}
        {bullet.text}
      </span>
    </li>
  )
}

/**
 * Takes the whole step rather than its bullets, because the numbers come from
 * the shapes drawn on the step's pictures and a list of bullets cannot see
 * them.
 */
export function BulletList({ step }: { step: Step }) {
  const visible = step.bullets.filter((bullet) => bullet.text.trim() !== '')
  if (visible.length === 0) return null

  const shapeNumbers = numberShapeColors(step)

  return (
    <ul className="bullets">
      {visible.map((bullet) => (
        <BulletItem key={bullet.id} bullet={bullet} shapeNumber={shapeNumbers[bullet.color]} />
      ))}
    </ul>
  )
}

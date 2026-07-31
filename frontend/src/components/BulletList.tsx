import type { ComponentType } from 'react'

import type { Bullet, BulletIcon } from '../domain/types'
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
        {bullet.icon && <span className="bullet__flag-label">{ICON_LABELS[bullet.icon]}</span>}
        {bullet.text}
      </span>
    </li>
  )
}

export function BulletList({ bullets }: { bullets: Bullet[] }) {
  const visible = bullets.filter((bullet) => bullet.text.trim() !== '')
  if (visible.length === 0) return null

  return (
    <ul className="bullets">
      {visible.map((bullet) => (
        <BulletItem key={bullet.id} bullet={bullet} />
      ))}
    </ul>
  )
}

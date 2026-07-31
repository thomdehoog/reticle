import type { ComponentType } from 'react'

import type { Bullet, BulletIcon } from '../domain/types'
import { IconCaution, IconNote, IconReminder, IconWarning } from './icons'

const ICON_COMPONENTS: Record<BulletIcon, ComponentType<{ size?: number }>> = {
  note: IconNote,
  caution: IconCaution,
  warning: IconWarning,
  reminder: IconReminder,
}

const ICON_LABELS: Record<BulletIcon, string> = {
  note: 'Note',
  caution: 'Caution',
  warning: 'Warning',
  reminder: 'Reminder',
}

/**
 * Renders one bullet's marker and text.
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
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <span className="bullet__marker">
        {Icon ? <Icon size={17} /> : <span className="bullet__dot" />}
      </span>
      <span className="bullet__text">
        {bullet.icon && <span className="visually-hidden">{ICON_LABELS[bullet.icon]}: </span>}
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

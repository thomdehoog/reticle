import { useState, type DragEvent } from 'react'

import { createBullet, indentBullet } from '../../domain/guide'
import type { Bullet, Media, Step } from '../../domain/types'
import { IconChevronDown, IconChevronUp, IconDrag, IconPlus, IconTrash } from '../icons'
import { BulletEditor } from './BulletEditor'
import { MediaSlots } from './MediaSlots'

interface StepEditorProps {
  step: Step
  number: number
  isFirst: boolean
  isLast: boolean
  canRemove: boolean
  focusBulletId: string | null
  uploading: boolean
  onChange: (step: Step) => void
  onRemove: () => void
  onMove: (delta: number) => void
  onFocusBullet: (bulletId: string | null) => void
  onUpload: (files: File[]) => void
  onDragStart: () => void
  onDragEnter: () => void
  onDragEnd: () => void
  dragging: boolean
  dropTarget: boolean
}

export function StepEditor({
  step,
  number,
  isFirst,
  isLast,
  canRemove,
  focusBulletId,
  uploading,
  onChange,
  onRemove,
  onMove,
  onFocusBullet,
  onUpload,
  onDragStart,
  onDragEnter,
  onDragEnd,
  dragging,
  dropTarget,
}: StepEditorProps) {
  const [draggable, setDraggable] = useState(false)

  function replaceBullet(index: number, bullet: Bullet) {
    const bullets = [...step.bullets]
    bullets[index] = bullet
    onChange({ ...step, bullets })
  }

  function splitAt(index: number) {
    const bullet = createBullet({ color: step.bullets[index].color, level: step.bullets[index].level })
    const bullets = [...step.bullets]
    bullets.splice(index + 1, 0, bullet)
    onChange({ ...step, bullets })
    onFocusBullet(bullet.id)
  }

  function removeAt(index: number, focusPrevious: boolean) {
    if (step.bullets.length === 1) return
    const bullets = step.bullets.filter((_, i) => i !== index)
    onChange({ ...step, bullets })
    if (focusPrevious) onFocusBullet(bullets[Math.max(index - 1, 0)].id)
  }

  function removeMedia(mediaId: string) {
    onChange({ ...step, media: step.media.filter((image: Media) => image.id !== mediaId) })
  }

  function onDragOver(event: DragEvent) {
    event.preventDefault()
  }

  return (
    <div
      className={[
        'editor-step',
        dragging ? 'editor-step--dragging' : '',
        dropTarget ? 'editor-step--drop-target' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragEnd={() => {
        setDraggable(false)
        onDragEnd()
      }}
    >
      <div className="editor-step__head">
        <button
          type="button"
          className="editor-step__handle"
          aria-label={`Reorder step ${number}`}
          onMouseDown={() => setDraggable(true)}
          onMouseUp={() => setDraggable(false)}
        >
          <IconDrag />
        </button>

        <span className="editor-step__number">{number}</span>

        <input
          className="editor-step__title-input"
          value={step.title}
          placeholder={`Step ${number} title (optional)`}
          onChange={(event) => onChange({ ...step, title: event.target.value })}
        />

        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Move step up"
          disabled={isFirst}
          onClick={() => onMove(-1)}
        >
          <IconChevronUp />
        </button>
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Move step down"
          disabled={isLast}
          onClick={() => onMove(1)}
        >
          <IconChevronDown />
        </button>
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Delete step"
          disabled={!canRemove}
          onClick={onRemove}
        >
          <IconTrash />
        </button>
      </div>

      <MediaSlots
        media={step.media}
        uploading={uploading}
        onAdd={onUpload}
        onRemove={removeMedia}
      />

      {step.bullets.map((bullet, index) => (
        <BulletEditor
          key={bullet.id}
          bullet={bullet}
          autoFocus={bullet.id === focusBulletId}
          onChange={(updated) => replaceBullet(index, updated)}
          onSplit={() => splitAt(index)}
          onRemoveEmpty={() => removeAt(index, true)}
          onIndent={(delta) => replaceBullet(index, indentBullet(bullet, delta))}
          onRemove={() => removeAt(index, false)}
        />
      ))}

      <button
        type="button"
        className="button button--ghost button--sm"
        onClick={() => splitAt(step.bullets.length - 1)}
      >
        <IconPlus size={14} />
        Add bullet
      </button>
    </div>
  )
}

/**
 * One step in the editor, all of it.
 *
 * A step is a title, some coloured points, and up to four pictures plus a video.
 * This file assembles those pieces into the card an author edits, and handles
 * dragging a step to a new position in the guide.
 *
 * It is a separate file mostly because a guide can have thirty steps: keeping one
 * step's editing entirely inside one component is what stops a change to step
 * four re-drawing the other twenty-nine.
 */

import { useState, type DragEvent } from 'react'

import { createBullet, indentBullet, numberShapeColors, promoteMedia } from '../../domain/guide'
import type { Bullet, Media, Step, StepKind } from '../../domain/types'
import { IconChevronDown, IconChevronUp, IconDrag, IconPlus, IconTrash } from '../icons'
import { BulletEditor } from './BulletEditor'
import { MediaSlots } from './MediaSlots'

interface StepEditorProps {
  step: Step
  /** null for a block that is not numbered. */
  number: number | null
  isFirst: boolean
  isLast: boolean
  canRemove: boolean
  focusBulletId: string | null
  uploading: boolean
  onChange: (step: Step) => void
  onRemove: () => void
  onMove: (delta: number) => void
  /** Adds a fresh block directly after this one. */
  onInsertAfter: () => void
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
  onInsertAfter,
  onFocusBullet,
  onUpload,
  onDragStart,
  onDragEnter,
  onDragEnd,
  dragging,
  dropTarget,
}: StepEditorProps) {
  const [draggable, setDraggable] = useState(false)

  /* The author sees the same numbers the reader will — on the pictures, which
     is now the only place either of them appears. */
  const shapeNumbers = numberShapeColors(step)

  /* What the card's controls call the thing they act on. An Info or Pinned
     block carries no number here, on its own card, or in the guide a reader
     opens, so it cannot be announced as "step 3" — and this is the wording the
     drag handle had already settled on. */
  const name = number === null ? 'this block' : `step ${number}`

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
          aria-label={`Reorder ${name}`}
          onMouseDown={() => setDraggable(true)}
          onMouseUp={() => setDraggable(false)}
        >
          <IconDrag />
        </button>

        <span className="editor-step__number">{number ?? '—'}</span>

        {/* Three words rather than a checkbox, because the choice is between
            three things and a checkbox can only ever offer two. It sits before
            the title so an author sees what kind of block they are typing into
            before they type. */}
        <select
          className="editor-step__kind"
          aria-label="What this block is"
          value={step.kind}
          onChange={(event) => onChange({ ...step, kind: event.target.value as StepKind })}
        >
          <option value="step">Step</option>
          <option value="info">Info</option>
          <option value="pinned">Pinned</option>
        </select>

        <div className="editor-step__actions">
          <button
            type="button"
            className="button button--ghost button--icon"
            aria-label={`Move ${name} up`}
            disabled={isFirst}
            onClick={() => onMove(-1)}
          >
            <IconChevronUp />
          </button>
          <button
            type="button"
            className="button button--ghost button--icon"
            aria-label={`Move ${name} down`}
            disabled={isLast}
            onClick={() => onMove(1)}
          >
            <IconChevronDown />
          </button>
          <button
            type="button"
            className="button button--ghost button--icon"
            aria-label={`Delete ${name}`}
            disabled={!canRemove}
            onClick={onRemove}
          >
            <IconTrash />
          </button>
        </div>

        {/* Its own full-width line, below the controls. It used to share the
            row with them, which on a 1440px screen left it 274px — and "Book
            the system and check the room", a perfectly ordinary ZMB step
            title, needs 330px, so an author could not see the end of the
            sentence they were typing. The phone layout had already dropped it
            to a line of its own; the fault was never about phones.

            Last in the markup as well as last on the screen, so that tabbing
            through the card visits the fields in the order they are drawn. */}
        <input
          className="editor-step__title-input"
          value={step.title}
          placeholder={number === null ? 'Title (optional)' : `Step ${number} title (optional)`}
          onChange={(event) => onChange({ ...step, title: event.target.value })}
        />
      </div>

      {/* The same three-part arrangement a reader gets: the large picture down
          the left, the thumbnails at the top of the column beside it, the
          points underneath those. It is placed by the grid in the stylesheet,
          which `.step__body` and this share so the two cannot drift — an
          author arranging a step should be looking at the step. */}
      <div className="editor-step__body">
        <MediaSlots
          media={step.media}
          video={step.video}
          shapeNumbers={shapeNumbers}
          uploading={uploading}
          onAdd={onUpload}
          onRemove={removeMedia}
          onPromote={(mediaId) => onChange({ ...step, media: promoteMedia(step.media, mediaId) })}
          onRemoveVideo={() => onChange({ ...step, video: null })}
          onUpdate={(updated) =>
            onChange(
              updated.id === step.video?.id
                ? { ...step, video: updated }
                : {
                    ...step,
                    media: step.media.map((image) => (image.id === updated.id ? updated : image)),
                  },
            )
          }
        />

        <div className="editor-step__points">
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
      </div>

      {/* Written where it is used. A guide is drafted in order and corrected
          out of order — "there should have been a step about the filter cube
          between these two" — and the alternative was to add one at the end and
          walk it up the list with the arrows, once per step in between. */}
      <button type="button" className="editor-step__insert" onClick={onInsertAfter}>
        <IconPlus size={14} />
        Add a step here
      </button>
    </div>
  )
}

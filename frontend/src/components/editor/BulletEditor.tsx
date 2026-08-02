/**
 * Writing the coloured points beside a step.
 *
 * This is the authoring side of `BulletList`. It lets somebody type a point,
 * choose its colour, indent it under the point above, and mark it as a Note,
 * Caution or Reminder.
 *
 * The colour picker matters more than it looks: the colour chosen here is the
 * same colour the author will draw on the picture, and that pairing is how a
 * reader knows which point refers to which part of the image.
 */

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentType,
  type KeyboardEvent,
} from 'react'

import {
  IconCaution,
  IconIndentLeft,
  IconIndentRight,
  IconNote,
  IconPalette,
  IconReminder,
  IconTrash,
} from '../icons'
import { MAX_BULLET_LEVEL } from '../../domain/guide'
import type { Bullet, BulletIcon } from '../../domain/types'
import { BULLET_COLOR_ORDER, BULLET_FLAG_LABELS } from '../../domain/palette'

const COLORS = BULLET_COLOR_ORDER

const ICON_CHOICES: {
  value: BulletIcon | null
  label: string
  Icon: ComponentType<{ size?: number }> | null
}[] = [
  { value: null, label: 'Plain bullet', Icon: null },
  { value: 'note', label: 'Note', Icon: IconNote },
  { value: 'caution', label: 'Caution', Icon: IconCaution },
  { value: 'reminder', label: 'Reminder', Icon: IconReminder },
]

interface BulletEditorProps {
  bullet: Bullet
  /** The shape on this step's pictures that this bullet's colour belongs to. */
  shapeNumber?: number
  autoFocus: boolean
  onChange: (bullet: Bullet) => void
  onSplit: () => void
  onRemoveEmpty: () => void
  onIndent: (delta: number) => void
  onRemove: () => void
}

/**
 * One editable bullet.
 *
 * The keyboard contract matters more than the buttons here: an author writing a
 * protocol should be able to type the whole step without reaching for the
 * mouse. Enter starts the next bullet, Backspace in an empty one removes it,
 * and Tab indents under the bullet above.
 *
 * Tab gives way once there is no indent left to change — outdenting a bullet
 * already at the margin, or indenting one already at the deepest level. That is
 * not a nicety: a Tab that is always swallowed means the caret can never leave
 * the field by keyboard, and a guide could not be written without a mouse at
 * all.
 */
export function BulletEditor({
  bullet,
  shapeNumber,
  autoFocus,
  onChange,
  onSplit,
  onRemoveEmpty,
  onIndent,
  onRemove,
}: BulletEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [pickerOpen, setPickerOpen] = useState(false)

  useLayoutEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [bullet.text])

  useEffect(() => {
    if (autoFocus) textareaRef.current?.focus()
  }, [autoFocus])

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      onSplit()
      return
    }
    if (event.key === 'Backspace' && bullet.text === '') {
      event.preventDefault()
      onRemoveEmpty()
      return
    }
    if (event.key === 'Tab') {
      // At either end of the range the indent would not move, so the key is
      // left to the browser and focus goes on to the next control.
      const wanted = bullet.level + (event.shiftKey ? -1 : 1)
      if (wanted < 0 || wanted > MAX_BULLET_LEVEL) return

      event.preventDefault()
      onIndent(event.shiftKey ? -1 : 1)
    }
  }

  /* The same classes the reader's bullet carries, so the flag word and the
     colour that go with a Caution appear here as the author types it. The
     alternative — plain black text in the editor, red bold in the guide — meant
     the one thing a caution exists to do was invisible while it was written. */
  const flag = bullet.icon
  const kindClasses = flag ? ` bullet--flagged bullet--kind-${flag}` : ''

  return (
    <div className={`editor-bullet bullet--color-${bullet.color}${kindClasses}`}>
      <div className="editor-bullet__picker">
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Bullet style"
          aria-expanded={pickerOpen}
          onClick={() => setPickerOpen((open) => !open)}
          style={{ marginLeft: `${bullet.level * 1.25}rem` }}
        >
          <BulletPreview bullet={bullet} shapeNumber={shapeNumber} />
        </button>

        {pickerOpen && (
          <BulletStylePicker
            bullet={bullet}
            onChange={onChange}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>

      {/* Spelled out in the editor because it is spelled out in the guide. It
          is not editable here — the flag is chosen from the picker beside it,
          which is the one place that decision is made. */}
      {flag && <span className="bullet__flag-label">{BULLET_FLAG_LABELS[flag]}</span>}

      <textarea
        ref={textareaRef}
        className="editor-bullet__text"
        rows={1}
        value={bullet.text}
        placeholder="Describe what to do…"
        onChange={(event) => onChange({ ...bullet, text: event.target.value })}
        onKeyDown={onKeyDown}
      />

      <div className="editor-bullet__actions">
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Outdent"
          disabled={bullet.level === 0}
          onClick={() => onIndent(-1)}
        >
          <IconIndentLeft />
        </button>
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Indent"
          disabled={bullet.level === 2}
          onClick={() => onIndent(1)}
        >
          <IconIndentRight />
        </button>
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Delete bullet"
          onClick={onRemove}
        >
          <IconTrash />
        </button>
      </div>
    </div>
  )
}

function BulletPreview({ bullet, shapeNumber }: { bullet: Bullet; shapeNumber?: number }) {
  if (shapeNumber !== undefined) return <span className="bullet__number">{shapeNumber}</span>

  const choice = ICON_CHOICES.find((candidate) => candidate.value === bullet.icon)
  if (choice?.Icon) return <choice.Icon size={16} />
  return <span className="bullet__dot" />
}

function BulletStylePicker({
  bullet,
  onChange,
  onClose,
}: {
  bullet: Bullet
  onChange: (bullet: Bullet) => void
  onClose: () => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onPointerDown(event: MouseEvent) {
      if (!ref.current?.contains(event.target as Node)) onClose()
    }
    function onKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  return (
    <div className="popover" ref={ref}>
      <div className="swatches">
        {COLORS.map((color) => (
          <button
            key={color}
            type="button"
            className={`swatch bullet--color-${color}`}
            aria-label={color}
            aria-pressed={bullet.color === color}
            onClick={() => onChange({ ...bullet, color })}
          />
        ))}
      </div>
      <div className="popover__section">
        {ICON_CHOICES.map((choice) => (
          <button
            key={choice.label}
            type="button"
            className="popover__item"
            aria-pressed={bullet.icon === choice.value}
            onClick={() => {
              onChange({ ...bullet, icon: choice.value })
              onClose()
            }}
          >
            {choice.Icon ? <choice.Icon size={16} /> : <IconPalette size={16} />}
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  )
}

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
import type { Bullet, BulletIcon } from '../../domain/types'
import { BULLET_COLOR_ORDER } from '../../domain/palette'

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
 * and Tab changes indent rather than leaving the field.
 */
export function BulletEditor({
  bullet,
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
      event.preventDefault()
      onIndent(event.shiftKey ? -1 : 1)
    }
  }

  return (
    <div className={`editor-bullet bullet--color-${bullet.color}`}>
      <div className="editor-bullet__picker">
        <button
          type="button"
          className="button button--ghost button--icon"
          aria-label="Bullet style"
          aria-expanded={pickerOpen}
          onClick={() => setPickerOpen((open) => !open)}
          style={{ marginLeft: `${bullet.level * 1.25}rem` }}
        >
          <BulletPreview bullet={bullet} />
        </button>

        {pickerOpen && (
          <BulletStylePicker
            bullet={bullet}
            onChange={onChange}
            onClose={() => setPickerOpen(false)}
          />
        )}
      </div>

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

function BulletPreview({ bullet }: { bullet: Bullet }) {
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

/**
 * Small presentational primitives shared across pages.
 *
 * These exist so that a status badge or an error message looks and behaves the
 * same everywhere without each page reinventing it, which is the usual way an
 * internal tool drifts into looking unfinished.
 */

import {
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'

import { ApiError } from '../api/client'
import { DIFFICULTY_LABELS, DIFFICULTY_ORDER } from '../domain/guide'
import type { ContentStatus, Difficulty } from '../domain/types'
import { IconClose } from './icons'

const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: 'Draft',
  published: 'Published',
  archived: 'Archived',
}

export function StatusBadge({ status }: { status: ContentStatus }) {
  return <span className={`badge badge--${status}`}>{STATUS_LABELS[status]}</span>
}

/**
 * Difficulty as a row of five marks rather than as a small-caps label and a
 * word underneath it.
 *
 * The word stays beside the marks. Five bars on their own would need a legend,
 * and somebody deciding whether to start a procedure now or after lunch should
 * not have to learn a scale first — the picture makes the level comparable at a
 * glance, the word makes it unambiguous.
 */
export function DifficultyMeter({ difficulty }: { difficulty: Difficulty }) {
  const level = DIFFICULTY_ORDER.indexOf(difficulty) + 1

  return (
    <span className="difficulty">
      <span className="difficulty__bars" aria-hidden="true">
        {DIFFICULTY_ORDER.map((step, index) => (
          <span
            key={step}
            className={`difficulty__bar${index < level ? ' difficulty__bar--filled' : ''}`}
          />
        ))}
      </span>
      {DIFFICULTY_LABELS[difficulty]}
    </span>
  )
}

export function Spinner() {
  return (
    <div className="spinner" role="status">
      Loading…
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>
}

/**
 * Turns whatever was thrown into something a microscopist can act on. Unknown
 * failures still surface rather than being swallowed, because a silent no-op is
 * the worst possible outcome for someone who just clicked Publish.
 */
export function ErrorAlert({ error }: { error: unknown }) {
  if (!error) return null

  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : 'Something went wrong.'

  return (
    <div className="alert alert--error" role="alert">
      {message}
    </div>
  )
}

/**
 * A textarea that grows to fit what it holds.
 *
 * A fixed-height box silently clips an introduction halfway through a sentence,
 * which reads as data loss even though the text is safe — the author simply
 * cannot see what they wrote without scrolling inside a small box.
 */
export function AutoTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null)

  useLayoutEffect(() => {
    const textarea = ref.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [props.value])

  return <textarea ref={ref} style={{ overflow: 'hidden' }} {...props} />
}

interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
  /** Set when a control elsewhere names this panel through `aria-controls`. */
  id?: string
}

const FOCUSABLE = 'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * A dialog that keeps the keyboard inside it.
 *
 * `aria-modal` tells assistive technology that the page behind is inert; it
 * does nothing whatever to the Tab order, so the keys have to be caught here.
 * Without that, Tab walks out of the dialog and into the form underneath — and
 * the next keystroke goes somewhere the author cannot see. Closing hands focus
 * back to whatever opened the dialog, because dropping it on `<body>` sends the
 * next Tab to the top of the page.
 */
export function Modal({ title, onClose, children, id }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const panel = panelRef.current
    const opener = document.activeElement as HTMLElement | null

    function stops(): HTMLElement[] {
      const found = panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []
      return [...found].filter((element) => !element.hasAttribute('disabled'))
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose()
        return
      }
      if (event.key !== 'Tab') return

      const inside = stops()
      if (inside.length === 0) return

      const first = inside[0]
      const last = inside[inside.length - 1]
      const active = document.activeElement

      if (event.shiftKey && (active === first || !panel?.contains(active))) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    stops()[0]?.focus()

    return () => {
      document.removeEventListener('keydown', onKeyDown)
      opener?.focus()
    }
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
        id={id}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={panelRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal__head">
          <h2>{title}</h2>
          <button type="button" className="button button--ghost button--icon" onClick={onClose}>
            <IconClose title="Close" />
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  )
}

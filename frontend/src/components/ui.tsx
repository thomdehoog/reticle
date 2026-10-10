/**
 * Small presentational primitives shared across pages.
 *
 * These exist so that a status badge or an error message looks and behaves the
 * same everywhere without each page reinventing it, which is the usual way an
 * internal tool drifts into looking unfinished.
 */

import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type TextareaHTMLAttributes,
} from 'react'

import { ApiError } from '../api/client'
import type { ContentStatus } from '../domain/types'
import { IconClose } from './icons'

const STATUS_LABELS: Record<ContentStatus, string> = {
  draft: 'Draft',
  in_review: 'In review',
  published: 'Published',
  archived: 'Archived',
}

export function StatusBadge({ status }: { status: ContentStatus }) {
  return <span className={`badge badge--${status}`}>{STATUS_LABELS[status]}</span>
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      {label}
    </div>
  )
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="empty-state">{children}</div>
}

/**
 * Says, on a reader screen, that what is shown is not what readers get.
 *
 * The badge beside the title says the same thing in one word; this says what
 * it means, to the author who is about to send a colleague the link.
 */
export function DraftNotice({ noun }: { noun: string }) {
  return (
    <div className="alert alert--info" role="note">
      <strong>This {noun} is a draft.</strong> Only authors can see it; readers will not find it
      until it is published.
    </div>
  )
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
}

const FOCUSABLE =
  'a[href], button:not(:disabled), input:not(:disabled):not([type="hidden"]), ' +
  'select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'

/** What Tab can reach inside an element, in order, leaving out anything not drawn. */
function focusableWithin(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => !element.hidden && element.closest('[hidden]') === null,
  )
}

/**
 * A dialog that behaves like one for a keyboard.
 *
 * Focus moves into it when it opens — to its first field, since every dialog
 * here exists to ask for something — stays inside while it is open, and goes
 * back to whatever opened it when it closes. Without the last part, closing a
 * dialog drops a keyboard user at the top of the page, a long way from the
 * step they were editing.
 */
export function Modal({ title, onClose, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  /* Callers pass a fresh function on most renders. Reading it through a ref
     keeps the effects below to "once per dialog": re-running them would pull
     focus back to the first field every time the parent re-rendered. */
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const panel = panelRef.current
    const first = bodyRef.current ? focusableWithin(bodyRef.current)[0] : undefined
    ;(first ?? panel)?.focus()

    return () => {
      if (opener?.isConnected) opener.focus()
    }
  }, [])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const panel = panelRef.current
      if (!panel) return

      /* Dialogs can stack — the wiki editor's guide-list dialog has a tag
         picker, the step editor an annotation dialog. Only the one on top
         answers the keyboard. */
      const open = document.querySelectorAll('.modal')
      if (open[open.length - 1] !== panel) return

      if (event.key === 'Escape') {
        if (event.defaultPrevented) return
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') return

      const stops = focusableWithin(panel)
      if (stops.length === 0) {
        event.preventDefault()
        return
      }
      const first = stops[0]
      const last = stops[stops.length - 1]
      const active = document.activeElement

      if (!panel.contains(active)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  return (
    <div className="modal-backdrop" onMouseDown={() => closeRef.current()}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        ref={panelRef}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="modal__head">
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            className="button button--ghost button--icon"
            aria-label="Close"
            onClick={onClose}
          >
            <IconClose />
          </button>
        </div>
        <div className="modal__body" ref={bodyRef}>
          {children}
        </div>
      </div>
    </div>
  )
}

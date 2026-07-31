/**
 * Small presentational primitives shared across pages.
 *
 * These exist so that a status badge or an error message looks and behaves the
 * same everywhere without each page reinventing it, which is the usual way an
 * internal tool drifts into looking unfinished.
 */

import { useEffect, useRef, type ReactNode } from 'react'

import { ApiError } from '../api/client'
import type { GuideStatus } from '../domain/types'
import { IconClose } from './icons'

const STATUS_LABELS: Record<GuideStatus, string> = {
  draft: 'Draft',
  in_review: 'In review',
  published: 'Published',
  archived: 'Archived',
}

export function StatusBadge({ status }: { status: GuideStatus }) {
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

interface ModalProps {
  title: string
  onClose: () => void
  children: ReactNode
}

export function Modal({ title, onClose, children }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    panelRef.current?.querySelector<HTMLElement>('input, select, textarea, button')?.focus()
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div
        className="modal"
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

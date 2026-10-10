/**
 * The editing copy of a document, and the autosave that follows it.
 *
 * Shared by the guide editor and the wiki editor, which need the same thing:
 * the author's copy lives in local state, every change schedules a debounced
 * whole-document save, and each save carries the `updatedAt` this editor last
 * saw so the server can refuse it if a colleague saved in the meantime.
 *
 * The hook is seeded once, from `initial`, and never looks at it again. That is
 * what keeps a cache update or background refetch from replacing text the
 * author has typed but not yet saved.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import type { ContentStatus } from '../domain/types'

export const AUTOSAVE_DELAY_MS = 1200

export type SaveState = 'clean' | 'pending' | 'saving' | 'saved' | 'error'

/** The fields a save returns that the server, not the author, decides. */
export interface ServerOwned {
  id: string
  slug: string
  status: ContentStatus
  version: number
  updatedAt: string
  publishedAt: string | null
}

/**
 * Keeps the author's content and takes the fields only the server sets — above
 * all `updatedAt`, without which the next save would conflict with the write
 * that produced this response.
 */
function withServerFields<T extends ServerOwned>(local: T, server: T): T {
  return {
    ...local,
    slug: server.slug,
    status: server.status,
    version: server.version,
    updatedAt: server.updatedAt,
    publishedAt: server.publishedAt,
  }
}

interface AutosaveOptions<T> {
  initial: T
  /** Writes the whole document and resolves to the server's copy of it. */
  save: (document: T) => Promise<T>
  delayMs?: number
}

export interface Autosave<T> {
  document: T
  /** Applies an edit and schedules a save. */
  change: (mutator: (current: T) => T) => void
  saveState: SaveState
  error: unknown
  /** True when the last save was refused because someone else saved first. */
  conflicted: boolean
  /**
   * Saves immediately and resolves to the stored document, for actions that
   * must act on exactly what is on screen — publishing above all. Rejects if
   * the save does, having already recorded the error.
   */
  saveNow: () => Promise<T>
  /**
   * Takes in the server's copy after an action that changed it there — publish,
   * unpublish — without discarding anything typed while that was in progress.
   */
  adopt: (document: T) => void
  /** Replaces the document outright and marks it clean, discarding local edits. */
  reset: (document: T) => void
  /** Shows a failure from a related action (an upload, a publish) in the same place. */
  reportError: (error: unknown) => void
}

function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.code === 'conflict'
}

export function useAutosave<T extends ServerOwned>({
  initial,
  save,
  delayMs = AUTOSAVE_DELAY_MS,
}: AutosaveOptions<T>): Autosave<T> {
  const [doc, setDoc] = useState(initial)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [error, setError] = useState<unknown>(null)

  /* Refs mirror what the timers and the unmount handler need to read: they run
     outside the render that scheduled them and must see the latest values. */
  const docRef = useRef(doc)
  const dirtyRef = useRef(false)
  const inFlightRef = useRef<Promise<unknown> | null>(null)
  const conflictedRef = useRef(false)
  const saveRef = useRef(save)
  const mountedRef = useRef(true)
  saveRef.current = save

  const apply = useCallback((next: T) => {
    docRef.current = next
    setDoc(next)
  }, [])

  const change = useCallback(
    (mutator: (current: T) => T) => {
      apply(mutator(docRef.current))
      dirtyRef.current = true
      setSaveState('pending')
    },
    [apply],
  )

  /**
   * One save at a time. Two overlapping writes would both carry the same
   * `expectedUpdatedAt`, and the second would be refused as a conflict with
   * the author's own first — so a save that is due while another is still in
   * the air waits for it and then sends whatever is current.
   */
  const persist = useCallback(async (): Promise<T> => {
    while (inFlightRef.current) {
      await inFlightRef.current.catch(() => undefined)
    }

    const sent = docRef.current
    dirtyRef.current = false
    if (mountedRef.current) {
      setSaveState('saving')
      setError(null)
    }

    const request = saveRef.current(sent)
    inFlightRef.current = request

    try {
      const saved = await request
      conflictedRef.current = false

      /* If the author kept typing while the request was out, their text stays. */
      const next = dirtyRef.current ? withServerFields(docRef.current, saved) : saved
      docRef.current = next

      if (mountedRef.current) {
        setDoc(next)
        setSaveState(dirtyRef.current ? 'pending' : 'saved')
      }
      return saved
    } catch (cause) {
      dirtyRef.current = true
      conflictedRef.current = isConflict(cause)
      if (mountedRef.current) {
        setError(cause)
        setSaveState('error')
      }
      throw cause
    } finally {
      if (inFlightRef.current === request) inFlightRef.current = null
    }
  }, [])

  /* The debounce. Re-armed by every change to the document — including the one
     a finished save makes — so edits typed during a save are picked up without
     a second mechanism. */
  useEffect(() => {
    if (!dirtyRef.current || inFlightRef.current) return

    const timer = setTimeout(() => {
      if (dirtyRef.current) void persist().catch(() => undefined)
    }, delayMs)

    return () => clearTimeout(timer)
  }, [doc, delayMs, persist])

  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      /* A save still in the air counts: the browser may drop the request with
         the page, and nothing would be left to send it again. */
      if (dirtyRef.current || inFlightRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  /**
   * Leaving the editor inside the app — a click on the breadcrumb a second
   * after the last keystroke — is not a page unload, so nothing would warn and
   * the pending debounce would simply be cancelled. Send it instead. After a
   * conflict there is nothing to send: the server has already said it will not
   * take this copy.
   */
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (dirtyRef.current && !conflictedRef.current) void persist().catch(() => undefined)
    }
  }, [persist])

  const adopt = useCallback(
    (server: T) => {
      apply(dirtyRef.current ? withServerFields(docRef.current, server) : server)
    },
    [apply],
  )

  const reset = useCallback(
    (next: T) => {
      dirtyRef.current = false
      conflictedRef.current = false
      apply(next)
      setError(null)
      setSaveState('clean')
    },
    [apply],
  )

  const reportError = useCallback((cause: unknown) => {
    setError(cause)
  }, [])

  return {
    document: doc,
    change,
    saveState,
    error,
    conflicted: isConflict(error),
    saveNow: persist,
    adopt,
    reset,
    reportError,
  }
}

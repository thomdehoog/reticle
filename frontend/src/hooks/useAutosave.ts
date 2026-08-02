/**
 * Deciding when to save what somebody is typing.
 *
 * The editors have no Save button. That is a deliberate choice - an author at a
 * bench should not have to remember one - but it means this file is the only
 * thing standing between them and losing their work, so it is worth reading
 * carefully.
 *
 * Saving on every keystroke would send a request per character. Waiting until
 * they stop typing is the usual answer, and on its own it is a trap: somebody
 * dictating a long procedure never pauses for long enough, so "wait until they
 * stop" can mean "never". This waits for a pause, **and** saves anyway once a
 * few seconds have passed regardless.
 *
 * It also saves when the editor closes. The browser's own "you have unsaved
 * changes" warning only fires when the whole tab is closing; clicking a link
 * inside the application does not close the tab, so without this, clicking
 * "Guides" in the breadcrumb after typing would throw the typing away with no
 * warning at all.
 */

import { useEffect, useRef } from 'react'

export const AUTOSAVE_PAUSE_MS = 1200

export const AUTOSAVE_MAX_WAIT_MS = 5000

interface Options {
  /** Changes on every edit. A change restarts the pause timer. */
  document: unknown
  /** Whether there is anything worth saving right now. */
  isDirty: () => boolean
  /** Performs the save. Called at most once per pause. */
  save: () => void
  pauseMs?: number
  maxWaitMs?: number
}

export function useAutosave({
  document,
  isDirty,
  save,
  pauseMs = AUTOSAVE_PAUSE_MS,
  maxWaitMs = AUTOSAVE_MAX_WAIT_MS,
}: Options): void {
  // Held in refs so that changing the save function - which happens on every
  // render, because it closes over the document - does not itself restart the
  // timer. Only a change to the document should do that.
  //
  // They are updated in an effect rather than during render. Effects run after
  // React has finished drawing, and a timer can only fire later still, so the
  // callbacks are always current by the time anything reads them.
  const saveNow = useRef(save)
  const dirty = useRef(isDirty)

  useEffect(() => {
    saveNow.current = save
    dirty.current = isDirty
  })

  const unsavedSince = useRef<number | null>(null)

  useEffect(() => {
    if (!dirty.current()) {
      unsavedSince.current = null
      return
    }

    if (unsavedSince.current === null) unsavedSince.current = Date.now()

    // Normally wait for a pause. But if edits have been arriving continuously
    // for maxWaitMs, stop waiting for one that may never come.
    const waitedSoFar = Date.now() - unsavedSince.current
    const wait = Math.max(0, Math.min(pauseMs, maxWaitMs - waitedSoFar))

    const timer = setTimeout(() => {
      unsavedSince.current = null
      saveNow.current()
    }, wait)

    return () => clearTimeout(timer)
  }, [document, pauseMs, maxWaitMs])

  useEffect(() => {
    // Runs when the editor closes. The request is sent and its answer is never
    // read, because this component is going away - but the work reaches the
    // server, which is the whole point.
    return () => {
      if (dirty.current()) saveNow.current()
    }
  }, [])
}

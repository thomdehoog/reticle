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
 * warning at all. That save has no screen left to report a failure on, which is
 * what the note at the bottom of this file is for.
 */

import { useEffect, useRef } from 'react'

export const AUTOSAVE_PAUSE_MS = 1200

export const AUTOSAVE_MAX_WAIT_MS = 5000

interface Options {
  /** Changes on every edit. A change restarts the pause timer. */
  snapshot: unknown
  /** Whether there is anything worth saving right now. */
  isDirty: () => boolean
  /** Performs the save. Called at most once per pause. */
  save: () => void
}

export function useAutosave({ snapshot, isDirty, save }: Options): void {
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
    // for AUTOSAVE_MAX_WAIT_MS, stop waiting for one that may never come.
    const waitedSoFar = Date.now() - unsavedSince.current
    const wait = Math.max(0, Math.min(AUTOSAVE_PAUSE_MS, AUTOSAVE_MAX_WAIT_MS - waitedSoFar))

    const timer = setTimeout(() => {
      unsavedSince.current = null
      // Asked again rather than assumed from when the timer was set. Publishing
      // takes the work first and clears the flag before it awaits; a timer that
      // fired anyway would send a second write carrying the same
      // updatedAt, and the server answers the loser of that pair with a
      // conflict - telling an author working alone that a colleague edited
      // their guide.
      if (dirty.current()) saveNow.current()
    }, wait)

    return () => clearTimeout(timer)
  }, [snapshot])

  useEffect(() => {
    // Runs when the editor closes, so the work reaches the server even though
    // this component is going away.
    return () => {
      if (dirty.current()) saveNow.current()
    }
  }, [])
}

/**
 * A note that a document's last write did not land.
 *
 * A save that fails while the editor is on screen says so on the screen. The
 * save fired as the editor closes has nothing left to say it on, so the failure
 * is written down here and the editor tells the author the next time they open
 * that document. Without it, a guide typed and then navigated away from can be
 * lost in complete silence.
 *
 * sessionStorage rather than localStorage: the note is about this sitting at
 * this machine, and a stale one a fortnight later would only frighten somebody.
 */
const FAILED_SAVE_PREFIX = 'reticle.failed-save.'

export function rememberFailedSave(documentId: string, message: string): void {
  sessionStorage.setItem(FAILED_SAVE_PREFIX + documentId, message)
}

export function readFailedSave(documentId: string): string | null {
  return sessionStorage.getItem(FAILED_SAVE_PREFIX + documentId)
}

export function forgetFailedSave(documentId: string): void {
  sessionStorage.removeItem(FAILED_SAVE_PREFIX + documentId)
}

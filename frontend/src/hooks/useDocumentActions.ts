/**
 * Publish, unpublish, discard and archive for a document open in an editor.
 *
 * These are the same four moves for a guide and for a wiki page; only the
 * endpoints and the publish-time checks differ, so those are passed in.
 */

import { useState } from 'react'

import { ApiError } from '../api/client'
import type { Autosave, ServerOwned } from './useAutosave'

/**
 * Runs one of the actions themselves, as opposed to the save before it.
 *
 * The editor reads a `conflict` as "a colleague saved first" and offers their
 * version, which is right for a save and wrong here: the server also answers
 * 409 when an action no longer applies — discarding the changes of something
 * that was unpublished a moment ago. That refusal is passed on in the server's
 * own words instead.
 */
async function acting<R>(work: () => Promise<R>): Promise<R> {
  try {
    return await work()
  } catch (cause) {
    if (cause instanceof ApiError && cause.code === 'conflict') throw new Error(cause.message)
    throw cause
  }
}

export type DocumentAction = 'publishing' | 'unpublishing' | 'discarding' | 'archiving'

interface DocumentActionsOptions<T> {
  autosave: Autosave<T>
  /** Returns false to stop a publish; it is expected to say why on screen itself. */
  readyToPublish: () => boolean
  publish: (id: string) => Promise<T>
  unpublish: (id: string) => Promise<T>
  /** Replaces the working copy with the published version and resolves to it. */
  revert: (id: string) => Promise<T>
  archive: (document: T) => Promise<void>
  onPublished: (published: T) => void
  /** Called with the restored document, in case the editor shows it differently. */
  onDiscarded?: (restored: T) => T
  onArchived: () => void
  /** Asked before archiving, which is the one action here an author cannot undo. */
  archiveWarning: string
  /** Asked before discarding; given the version that will be restored. */
  discardWarning: (version: number) => string
}

export function useDocumentActions<T extends ServerOwned>({
  autosave,
  readyToPublish,
  publish,
  unpublish,
  revert,
  archive,
  onPublished,
  onDiscarded,
  onArchived,
  archiveWarning,
  discardWarning,
}: DocumentActionsOptions<T>) {
  const [busy, setBusy] = useState<DocumentAction | null>(null)

  async function run(action: DocumentAction, work: () => Promise<void>) {
    setBusy(action)
    autosave.reportError(null)
    try {
      await work()
    } catch (cause) {
      autosave.reportError(cause)
    } finally {
      setBusy(null)
    }
  }

  return {
    busy,

    /**
     * Saves first, so what gets published is exactly what is on screen rather
     * than whatever the last autosave happened to catch.
     */
    publish: () => {
      if (!readyToPublish()) return
      void run('publishing', async () => {
        const saved = await autosave.saveNow()
        const published = await acting(() => publish(saved.id))
        autosave.adopt(published)
        onPublished(published)
      })
    },

    unpublish: () => {
      void run('unpublishing', async () => {
        const saved = await autosave.saveNow()
        autosave.adopt(await acting(() => unpublish(saved.id)))
      })
    },

    /**
     * Throws away everything since the last publish. What is on screen and
     * not yet saved goes too, without being sent first: saving a change in
     * order to discard it would only risk a conflict over text nobody wants.
     * A save that had already left is waited for, so that it cannot arrive
     * after the restore and put the discarded text back.
     */
    discard: () => {
      if (!window.confirm(discardWarning(autosave.document.version))) return
      void run('discarding', async () => {
        autosave.reset(autosave.document)
        await autosave.settled()
        const restored = await acting(() => revert(autosave.document.id))
        autosave.reset(onDiscarded ? onDiscarded(restored) : restored)
      })
    },

    archive: () => {
      if (!window.confirm(archiveWarning)) return
      void run('archiving', async () => {
        await archive(autosave.document)
        /* Marked clean so that leaving the editor does not try to save a
           document the server has just retired. */
        autosave.reset(autosave.document)
        onArchived()
      })
    },
  }
}

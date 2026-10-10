/**
 * Publish, unpublish and archive for a document open in an editor.
 *
 * These are the same three moves for a guide and for a wiki page; only the
 * endpoints and the publish-time checks differ, so those are passed in.
 */

import { useState } from 'react'

import type { Autosave, ServerOwned } from './useAutosave'

export type DocumentAction = 'publishing' | 'unpublishing' | 'archiving'

interface DocumentActionsOptions<T> {
  autosave: Autosave<T>
  /** Returns false to stop a publish; it is expected to say why on screen itself. */
  readyToPublish: () => boolean
  publish: (id: string) => Promise<T>
  unpublish: (id: string) => Promise<T>
  archive: (document: T) => Promise<void>
  onPublished: (published: T) => void
  onArchived: () => void
  /** Asked before archiving, which is the one action here an author cannot undo. */
  archiveWarning: string
}

export function useDocumentActions<T extends ServerOwned>({
  autosave,
  readyToPublish,
  publish,
  unpublish,
  archive,
  onPublished,
  onArchived,
  archiveWarning,
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
        const published = await publish(saved.id)
        autosave.adopt(published)
        onPublished(published)
      })
    },

    unpublish: () => {
      void run('unpublishing', async () => {
        const saved = await autosave.saveNow()
        autosave.adopt(await unpublish(saved.id))
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

/**
 * Taking a guide or a page out of circulation.
 */

import { useState } from 'react'

import { useAuth } from '../../auth/AuthContext'
import type { ContentStatus } from '../../domain/types'
import { ErrorAlert, Modal } from '../ui'

/**
 * Taking something out of circulation.
 *
 * Two separate actions, because they answer two different questions. Unpublish
 * says "this is wrong, stop showing it while I fix it" and any author may do
 * it — a superseded laser interlock procedure needs to come down in seconds,
 * not after a discussion. Archive says "this should never have existed or never
 * will again", it is an administrator's call, and even then the server only
 * marks the document archived: nothing here deletes content, because at a
 * facility the reason a procedure was withdrawn is itself worth keeping.
 *
 * Both are behind a confirmation. They are irreversible from this screen and
 * they sit next to Publish.
 */
export function LifecycleActions({
  kind,
  status,
  onUnpublish,
  onArchive,
}: {
  kind: 'guide' | 'page'
  status: ContentStatus
  onUnpublish: () => Promise<void>
  onArchive: () => Promise<void>
}) {
  const { can } = useAuth()
  const [confirming, setConfirming] = useState<'unpublish' | 'archive' | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setConfirming(null)
    } catch (cause) {
      setError(cause)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {status === 'published' && (
        <button
          className="button"
          type="button"
          onClick={() => {
            setError(null)
            setConfirming('unpublish')
          }}
        >
          Unpublish
        </button>
      )}

      {can('admin') && status !== 'archived' && (
        <button
          className="button button--danger"
          type="button"
          onClick={() => {
            setError(null)
            setConfirming('archive')
          }}
        >
          Archive
        </button>
      )}

      {confirming === 'unpublish' && (
        <Modal title={`Unpublish this ${kind}?`} onClose={() => setConfirming(null)}>
          <ErrorAlert error={error} />
          <p>
            It goes back to draft. Readers stop seeing it immediately, the text stays exactly as it
            is, and publishing again restores it.
          </p>
          <div className="page-actions">
            <button
              className="button button--primary"
              type="button"
              disabled={busy}
              onClick={() => void run(onUnpublish)}
            >
              {busy ? 'Unpublishing…' : `Unpublish ${kind}`}
            </button>
            <button className="button" type="button" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}

      {confirming === 'archive' && (
        <Modal title={`Archive this ${kind}?`} onClose={() => setConfirming(null)}>
          <ErrorAlert error={error} />
          <p>
            Archiving hides the {kind} from everyone, including authors, and it disappears from
            listings and search. Nothing is deleted — an administrator can still find it in the
            database — but there is no way back to it from inside Reticle.
          </p>
          <div className="page-actions">
            <button
              className="button button--danger"
              type="button"
              disabled={busy}
              onClick={() => void run(onArchive)}
            >
              {busy ? 'Archiving…' : `Archive ${kind}`}
            </button>
            <button className="button" type="button" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

/**
 * What an author is offered when a colleague saved the same document first.
 *
 * Every write carries the `updatedAt` the editor last saw, and the server
 * refuses one whose timestamp is stale. That refusal is what stops two ZMB
 * staff overwriting each other, and it is also where the danger is: the editor
 * still holds the timestamp that was just rejected, so every later autosave
 * carries the same stale value and is refused too. Left there, the author types
 * on into a document that can never be saved again.
 *
 * So a refusal has to end in a decision, and this is where it is made. Keeping
 * your version adopts their timestamp so the next write is legal and replaces
 * their text; using theirs replaces yours. Only the second destroys anything,
 * which is why it is the one behind a confirmation and never the default —
 * and either way the author's own words are on screen as plain selectable text
 * first, because nothing here may discard work that cannot be copied out.
 */

import { useState } from 'react'

export function SaveConflict({
  kind,
  savedBy,
  savedAt,
  myVersion,
  onKeepMine,
  onUseTheirs,
}: {
  kind: 'guide' | 'page'
  savedBy: string
  savedAt: string
  /** The author's current text, already flattened for copying. */
  myVersion: string
  onKeepMine: () => void
  onUseTheirs: () => void
}) {
  const [confirming, setConfirming] = useState(false)

  return (
    <div className="alert alert--warning" role="alert">
      <p>
        <strong>Someone else saved this {kind} while you were editing.</strong> {savedBy} saved it
        at {new Date(savedAt).toLocaleString()}, so your recent changes have not been saved and
        their work is intact.
      </p>

      <details className="conflict__mine">
        <summary>What you wrote, to copy out before you choose</summary>
        <pre>{myVersion}</pre>
      </details>

      {confirming ? (
        <p className="conflict__choice">
          <strong>Everything you typed since they saved will be gone.</strong>
          <button className="button button--sm button--danger" type="button" onClick={onUseTheirs}>
            Discard my version
          </button>
          <button className="button button--sm" type="button" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </p>
      ) : (
        <p className="conflict__choice">
          <button className="button button--sm button--primary" type="button" onClick={onKeepMine}>
            Keep my version
          </button>
          <button className="button button--sm" type="button" onClick={() => setConfirming(true)}>
            Use theirs instead
          </button>
        </p>
      )}
    </div>
  )
}

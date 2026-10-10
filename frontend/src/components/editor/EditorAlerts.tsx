import { ErrorAlert } from '../ui'

interface EditorAlertsProps {
  /** "guide" or "page", for the wording. */
  noun: string
  error: unknown
  conflicted: boolean
  /** Fetches the colleague's version and replaces the local copy with it. */
  onReload: () => void
  /** Reasons the document cannot be published yet; empty when there are none. */
  issues: string[]
}

/**
 * Everything an editor has to tell its author about saving and publishing.
 *
 * A conflict gets its own message instead of the generic error: the author
 * needs to know that nothing was overwritten, and that the way forward is to
 * look at what their colleague did rather than to press save harder.
 */
export function EditorAlerts({ noun, error, conflicted, onReload, issues }: EditorAlertsProps) {
  return (
    <>
      {conflicted ? (
        <div className="alert alert--warning" role="alert">
          <strong>Someone else saved this {noun} while you were editing.</strong> To avoid
          overwriting their work, your recent changes have not been saved.{' '}
          <button className="button button--sm" type="button" onClick={onReload}>
            Reload their version
          </button>
        </div>
      ) : (
        <ErrorAlert error={error} />
      )}

      {issues.length > 0 && (
        <div className="alert alert--warning" role="alert">
          <strong>This {noun} is not ready to publish:</strong>
          <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
            {issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

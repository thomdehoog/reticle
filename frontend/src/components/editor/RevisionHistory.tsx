/**
 * The list of times a guide or a wiki page was published, and a way to read one.
 *
 * Every publish writes an immutable snapshot server-side, and this panel is how
 * an author opens one. That matters at a facility more than it might elsewhere.
 * If an instrument was damaged in March, the question is what the procedure
 * said in March, not what it says now that somebody has corrected it; and when
 * somebody asks "the protocol used to say 90 seconds, who changed it and when",
 * the answer is a version, a date and a name.
 *
 * Read-only on purpose. There is no restore button, because silently
 * overwriting the current text with a two-year-old procedure is exactly the
 * accident the version history exists to investigate. An author who wants an
 * old wording copies it across, and the new publish is recorded as its own
 * version.
 */

import { useState, type ReactNode } from 'react'

import type { RevisionSummary } from '../../api/reticle'
import { useAsync } from '../../hooks/useAsync'
import { ErrorAlert, Modal, Spinner } from '../ui'

export function RevisionHistory<T>({
  title,
  list,
  load,
  render,
  onClose,
}: {
  title: string
  list: () => Promise<RevisionSummary[]>
  load: (version: number) => Promise<T>
  render: (document: T) => ReactNode
  onClose: () => void
}) {
  const [version, setVersion] = useState<number | null>(null)
  const revisions = useAsync(list, [])
  const opened = useAsync(
    () => (version === null ? Promise.resolve(null) : load(version)),
    [version],
  )

  return (
    <Modal title={title} onClose={onClose}>
      {version === null ? (
        <>
          {revisions.loading && <Spinner />}
          <ErrorAlert error={revisions.error} />
          {!revisions.loading && (revisions.data ?? []).length === 0 && (
            <p>
              This has never been published, so there are no earlier versions yet. A version is
              written each time you publish.
            </p>
          )}
          {(revisions.data ?? []).length > 0 && (
            <ul className="revisions">
              {[...(revisions.data ?? [])]
                .sort((a, b) => b.version - a.version)
                .map((revision) => (
                  <li key={revision.version}>
                    <button
                      className="revisions__item"
                      type="button"
                      onClick={() => setVersion(revision.version)}
                    >
                      <span className="revisions__version">Version {revision.version}</span>
                      <span className="revisions__meta">
                        {new Date(revision.publishedAt).toLocaleString()} ·{' '}
                        {revision.publishedBy.displayName}
                      </span>
                    </button>
                  </li>
                ))}
            </ul>
          )}
        </>
      ) : (
        <>
          <div className="page-actions" style={{ marginBottom: '1rem' }}>
            <button className="button" type="button" onClick={() => setVersion(null)}>
              Back to all versions
            </button>
            <span className="save-state">Version {version}, as published</span>
          </div>
          {opened.loading && <Spinner />}
          <ErrorAlert error={opened.error} />
          {opened.data && <div className="revisions__preview">{render(opened.data)}</div>}
        </>
      )}
    </Modal>
  )
}

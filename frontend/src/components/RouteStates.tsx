/**
 * What the router shows in place of a screen: while one loads, when loading
 * failed, and when there is nothing at that address.
 *
 * Defined once and handed to the router as its defaults, so no page carries
 * its own spinner-or-error preamble and they cannot drift apart in wording.
 */

import { useQueryErrorResetBoundary } from '@tanstack/react-query'
import { Link, useRouter, type ErrorComponentProps } from '@tanstack/react-router'
import { useEffect } from 'react'

import { EmptyState, ErrorAlert, Spinner } from './ui'

export function RoutePending() {
  return <Spinner />
}

export function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  const queryErrors = useQueryErrorResetBoundary()

  /* A query that failed stays failed until it is told otherwise; without this
     "Try again" would re-render straight back into the same error. */
  useEffect(() => {
    queryErrors.reset()
  }, [queryErrors])

  return (
    <>
      <ErrorAlert error={error} />
      <div className="page-actions">
        <button
          className="button"
          type="button"
          onClick={() => {
            reset()
            void router.invalidate()
          }}
        >
          Try again
        </button>
        <Link className="button" to="/">
          Back to guides
        </Link>
      </div>
    </>
  )
}

/**
 * Deliberately says nothing about *why*. The server answers 404 both for what
 * does not exist and for a draft this reader may not see, precisely so that a
 * draft's existence is not given away — and this must not undo that.
 */
export function NotFound() {
  return (
    <EmptyState>
      <p>There is nothing here, or it is not published yet.</p>
      <p style={{ marginTop: '0.75rem' }}>
        <Link className="button" to="/">
          Back to guides
        </Link>
      </p>
    </EmptyState>
  )
}

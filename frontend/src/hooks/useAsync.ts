import { useCallback, useEffect, useState } from 'react'

interface AsyncState<T> {
  data: T | null
  error: unknown
  loading: boolean
  reload: () => void
}

interface Outcome<T> {
  data: T | null
  error: unknown
  loading: boolean
}

const PENDING: Outcome<never> = { data: null, error: null, loading: true }

/**
 * Runs an async loader and tracks its outcome.
 *
 * Results that arrive after the inputs changed are discarded, so a slow
 * response for the previous category cannot overwrite the one the user is
 * looking at now.
 *
 * The three values are one state object rather than three `useState` calls, and
 * that is not tidiness. Each transition here is a single `setState`, so a
 * completed load re-renders once instead of two or three times — and, more
 * importantly, the intermediate combinations never exist. With separate hooks
 * there is a moment after `setData` and before `setLoading(false)` where the
 * component holds both data and a loading flag, and every consumer has to be
 * written to survive a state that is not real.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [outcome, setOutcome] = useState<Outcome<T>>(PENDING)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    let current = true

    // Resetting to pending synchronously is deliberate, and it is why the
    // `set-state-in-effect` rule is suppressed rather than obeyed. Without it,
    // the previous inputs' data stays on screen until the new request
    // resolves — so switching category shows the old category's guides under
    // the new heading, which reads as wrong data rather than as loading. One
    // extra render is a cheaper problem than that.
    //
    // It is also skipped when already pending, which is the common case on
    // mount and costs nothing when it applies.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOutcome((previous) => (previous === PENDING ? previous : PENDING))

    loader()
      .then((result) => {
        if (current) setOutcome({ data: result, error: null, loading: false })
      })
      .catch((cause: unknown) => {
        if (current) setOutcome({ data: null, error: cause, loading: false })
      })

    return () => {
      current = false
    }
    // `loader` is intentionally absent: it is a fresh closure on every render,
    // so including it would re-run the request forever. `deps` is the caller's
    // statement of what the request actually depends on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { ...outcome, reload }
}

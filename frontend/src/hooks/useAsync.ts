import { useCallback, useEffect, useState } from 'react'

interface AsyncState<T> {
  data: T | null
  error: unknown
  loading: boolean
  reload: () => void
}

/**
 * Runs an async loader and tracks its outcome.
 *
 * Results that arrive after the inputs changed are discarded, so a slow
 * response for the previous category cannot overwrite the one the user is
 * looking at now.
 */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  useEffect(() => {
    let current = true
    setLoading(true)
    setError(null)

    loader()
      .then((result) => {
        if (!current) return
        setData(result)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (!current) return
        setError(cause)
        setLoading(false)
      })

    return () => {
      current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  return { data, error, loading, reload }
}

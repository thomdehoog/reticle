/**
 * Fetching a guide's PDF, and saying what is happening while it is made.
 *
 * The export is the most expensive thing a reader can ask the server for, so
 * the server rations it: a few at a time, and one per person. A request it
 * cannot start is answered at once with `rate_limited` and how long to wait.
 * This waits that long and asks again, a handful of times, and tells the
 * person so — instead of a download link that silently saves an error message
 * as "guide.pdf", which is what a plain `<a download>` did with that answer.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/client'
import { useApi } from '../api/context'
import type { ContentView } from '../domain/types'

/** How often a busy server is asked again before the person is told to come back. */
export const PDF_ATTEMPTS = 6
/** Used when the server says it is busy without saying for how long. */
export const PDF_RETRY_SECONDS = 5

export type PdfState =
  | { phase: 'idle' }
  | { phase: 'preparing' }
  | { phase: 'waiting'; message: string }
  | { phase: 'failed'; message: string }

/** Hands a file to the browser's download machinery. */
function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  /* Revoked a little later: some browsers start reading the blob only after
     the click handler has returned. */
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

function isBusy(cause: unknown): cause is ApiError {
  return cause instanceof ApiError && cause.code === 'rate_limited'
}

export function usePdfDownload(slug: string, view?: ContentView) {
  const api = useApi()
  const [state, setState] = useState<PdfState>({ phase: 'idle' })

  /* Leaving the page abandons the wait: nobody is there to receive the file,
     and a state update on an unmounted screen is only a warning to chase. */
  const alive = useRef(true)
  const timer = useRef<number | null>(null)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      if (timer.current !== null) window.clearTimeout(timer.current)
    }
  }, [])

  const start = useCallback(async () => {
    setState({ phase: 'preparing' })
    for (let attempt = 1; alive.current; attempt += 1) {
      try {
        const blob = await api.downloadGuidePdf(slug, view)
        if (!alive.current) return
        saveFile(blob, `${slug}.pdf`)
        setState({ phase: 'idle' })
        return
      } catch (cause) {
        if (!alive.current) return
        if (!isBusy(cause)) {
          const message =
            cause instanceof Error ? cause.message : 'The PDF could not be prepared.'
          setState({ phase: 'failed', message })
          return
        }
        if (attempt >= PDF_ATTEMPTS) {
          setState({
            phase: 'failed',
            message:
              'The server is still busy preparing other PDFs. Nothing is wrong with this ' +
              'guide — please try again in a minute.',
          })
          return
        }
        setState({ phase: 'waiting', message: `${cause.message} Trying again shortly…` })
        const seconds = cause.retryAfterSeconds ?? PDF_RETRY_SECONDS
        await new Promise<void>((resolve) => {
          timer.current = window.setTimeout(resolve, seconds * 1000)
        })
      }
    }
  }, [api, slug, view])

  return {
    state,
    busy: state.phase === 'preparing' || state.phase === 'waiting',
    start: () => void start(),
  }
}

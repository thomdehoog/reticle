import { useEffect, useRef } from 'react'

/**
 * Tells the server a guide or page has been read — once per time a reader
 * opens it.
 *
 * The ref is what makes it once: React's StrictMode runs effects twice in
 * development, and a re-render with the same id is not another read. A failure
 * is ignored on purpose, since nothing the reader is doing depends on the
 * counter and an error message about it would only be noise.
 */
export function useRecordView(id: string, record: (id: string) => Promise<void>): void {
  const recorded = useRef<string | null>(null)
  const recordRef = useRef(record)
  recordRef.current = record

  useEffect(() => {
    if (recorded.current === id) return
    recorded.current = id
    recordRef.current(id).catch(() => undefined)
  }, [id])
}

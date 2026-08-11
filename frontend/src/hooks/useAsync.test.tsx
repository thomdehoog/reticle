/**
 * The two refresh paths, held apart.
 *
 * Changing the inputs means the screen is about to show something else, and
 * the old data must go at once — stale guides under a fresh heading read as
 * wrong data, not as loading. Reloading the same inputs is the opposite: the
 * data on screen IS the current page, and blanking it paints a spinner over a
 * page that was fine — the flicker an author sees after every in-place edit.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useAsync } from './useAsync'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

describe('useAsync', () => {
  it('keeps the data on screen through a reload of the same inputs', async () => {
    const answers = [deferred<string>(), deferred<string>()]
    let call = 0
    const { result } = renderHook(() => useAsync(() => answers[call++].promise, []))

    answers[0].resolve('the first answer')
    await waitFor(() => expect(result.current.data).toBe('the first answer'))

    act(() => result.current.reload())

    /* The whole point: mid-reload, the page still has its data and is not
       "loading" — nothing for a screen to swap a spinner in for. */
    expect(result.current.data).toBe('the first answer')
    expect(result.current.loading).toBe(false)

    answers[1].resolve('the fresh answer')
    await waitFor(() => expect(result.current.data).toBe('the fresh answer'))
  })

  it('drops the data at once when the inputs change', async () => {
    const answers = [deferred<string>(), deferred<string>()]
    let call = 0
    const { result, rerender } = renderHook(({ id }) => useAsync(() => answers[call++].promise, [id]), {
      initialProps: { id: 'a' },
    })

    answers[0].resolve('what a shows')
    await waitFor(() => expect(result.current.data).toBe('what a shows'))

    rerender({ id: 'b' })

    /* New inputs, old data gone immediately: b must never wear a's answer. */
    expect(result.current.data).toBeNull()
    expect(result.current.loading).toBe(true)

    answers[1].resolve('what b shows')
    await waitFor(() => expect(result.current.data).toBe('what b shows'))
  })
})

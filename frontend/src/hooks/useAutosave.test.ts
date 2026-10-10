import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { AUTOSAVE_DELAY_MS, useAutosave } from './useAutosave'

interface Doc {
  id: string
  slug: string
  status: 'draft' | 'published'
  version: number
  updatedAt: string
  publishedAt: string | null
  hasUnpublishedChanges: boolean
  text: string
}

const INITIAL: Doc = {
  id: 'd1',
  slug: 'doc',
  status: 'draft',
  version: 0,
  updatedAt: 't0',
  publishedAt: null,
  hasUnpublishedChanges: false,
  text: 'a',
}

/** A save whose every call can be answered by hand, in whatever order a test needs. */
function controllableSave() {
  const calls: { sent: Doc; resolve: (saved: Doc) => void; reject: (cause: unknown) => void }[] = []
  const save = vi.fn(
    (sent: Doc) =>
      new Promise<Doc>((resolve, reject) => {
        calls.push({ sent, resolve, reject })
      }),
  )
  return { save, calls }
}

function setup(save: (doc: Doc) => Promise<Doc>) {
  return renderHook(() => useAutosave({ initial: INITIAL, save }))
}

const type = (text: string) => (current: Doc) => ({ ...current, text })

async function elapse(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('useAutosave', () => {
  it('saves nothing until something changes', async () => {
    const { save } = controllableSave()
    const { result } = setup(save)

    await elapse(AUTOSAVE_DELAY_MS * 3)

    expect(save).not.toHaveBeenCalled()
    expect(result.current.saveState).toBe('clean')
  })

  it('waits for a pause in typing, then sends the whole document once', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('ab')))
    await elapse(AUTOSAVE_DELAY_MS - 100)
    act(() => result.current.change(type('abc')))
    await elapse(AUTOSAVE_DELAY_MS - 100)
    expect(save).not.toHaveBeenCalled()
    expect(result.current.saveState).toBe('pending')

    await elapse(100)
    expect(save).toHaveBeenCalledTimes(1)
    expect(calls[0].sent).toEqual({ ...INITIAL, text: 'abc' })
    expect(result.current.saveState).toBe('saving')

    await act(async () => calls[0].resolve({ ...calls[0].sent, updatedAt: 't1' }))
    expect(result.current.saveState).toBe('saved')
    expect(result.current.document.updatedAt).toBe('t1')
  })

  it('keeps what was typed during a save, and takes only the server fields from the reply', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('first')))
    await elapse(AUTOSAVE_DELAY_MS)
    act(() => result.current.change(type('first and second')))

    await act(async () => calls[0].resolve({ ...calls[0].sent, updatedAt: 't1', slug: 'renamed' }))

    expect(result.current.document.text).toBe('first and second')
    expect(result.current.document.updatedAt).toBe('t1')
    expect(result.current.document.slug).toBe('renamed')
    expect(result.current.saveState).toBe('pending')
  })

  it('never has two saves in the air, so it cannot conflict with itself', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('first')))
    await elapse(AUTOSAVE_DELAY_MS)
    expect(save).toHaveBeenCalledTimes(1)

    /* The server is slow: a second debounce comes due while the first save is
       still out. Sent now, it would carry the same `updatedAt` as the first. */
    act(() => result.current.change(type('second')))
    await elapse(AUTOSAVE_DELAY_MS * 3)
    expect(save).toHaveBeenCalledTimes(1)

    await act(async () => calls[0].resolve({ ...calls[0].sent, updatedAt: 't1' }))
    await elapse(AUTOSAVE_DELAY_MS)

    expect(save).toHaveBeenCalledTimes(2)
    expect(calls[1].sent).toMatchObject({ text: 'second', updatedAt: 't1' })
  })

  it('reports a conflict and does not retry by itself', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('mine')))
    await elapse(AUTOSAVE_DELAY_MS)
    await act(async () => calls[0].reject(new ApiError('conflict', 'Someone else saved first.', 409)))

    expect(result.current.conflicted).toBe(true)
    expect(result.current.saveState).toBe('error')
    expect(result.current.document.text).toBe('mine')

    await elapse(AUTOSAVE_DELAY_MS * 5)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('tells a conflict apart from any other failed save', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('mine')))
    await elapse(AUTOSAVE_DELAY_MS)
    await act(async () => calls[0].reject(new ApiError('network_error', 'Offline.', 0)))

    expect(result.current.conflicted).toBe(false)
    expect(result.current.error).toBeInstanceOf(ApiError)
    expect(result.current.saveState).toBe('error')

    /* The next keystroke tries again, and success clears the error. */
    act(() => result.current.change(type('mine again')))
    await elapse(AUTOSAVE_DELAY_MS)
    await act(async () => calls[1].resolve({ ...calls[1].sent, updatedAt: 't1' }))

    expect(result.current.error).toBeNull()
    expect(result.current.saveState).toBe('saved')
  })

  it('saves on demand without waiting, and the pending debounce then has nothing to do', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('publish me')))
    let saved: Doc | undefined
    await act(async () => {
      const pending = result.current.saveNow()
      calls[0].resolve({ ...calls[0].sent, updatedAt: 't1' })
      saved = await pending
    })

    expect(saved).toMatchObject({ text: 'publish me', updatedAt: 't1' })
    await elapse(AUTOSAVE_DELAY_MS * 2)
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('makes a save on demand wait its turn behind one already in flight', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('first')))
    await elapse(AUTOSAVE_DELAY_MS)
    act(() => result.current.change(type('second')))

    let pending: Promise<Doc> | undefined
    act(() => {
      pending = result.current.saveNow()
    })
    expect(save).toHaveBeenCalledTimes(1)

    await act(async () => calls[0].resolve({ ...calls[0].sent, updatedAt: 't1' }))
    expect(save).toHaveBeenCalledTimes(2)
    expect(calls[1].sent).toMatchObject({ text: 'second', updatedAt: 't1' })

    await act(async () => {
      calls[1].resolve({ ...calls[1].sent, updatedAt: 't2' })
      await pending
    })
    expect(result.current.saveState).toBe('saved')
  })

  it('ignores a new `initial` once editing has begun', async () => {
    const { save } = controllableSave()
    const { result, rerender } = renderHook(
      ({ initial }: { initial: Doc }) => useAutosave({ initial, save }),
      { initialProps: { initial: INITIAL } },
    )

    act(() => result.current.change(type('unsaved')))
    rerender({ initial: { ...INITIAL, text: 'refetched', updatedAt: 't9' } })

    expect(result.current.document.text).toBe('unsaved')
    expect(result.current.document.updatedAt).toBe('t0')
  })

  it('adopts a server copy without dropping unsaved typing', async () => {
    const { save } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.adopt({ ...INITIAL, status: 'published', version: 1, updatedAt: 't1' }))
    expect(result.current.document).toMatchObject({ status: 'published', text: 'a' })

    act(() => result.current.change(type('typed since')))
    act(() => result.current.adopt({ ...INITIAL, status: 'draft', version: 1, updatedAt: 't2' }))
    expect(result.current.document).toMatchObject({
      status: 'draft',
      updatedAt: 't2',
      text: 'typed since',
    })
  })

  it('discards local edits on reset, and saves nothing for them', async () => {
    const { save } = controllableSave()
    const { result } = setup(save)

    act(() => result.current.change(type('to be thrown away')))
    act(() => result.current.reset({ ...INITIAL, text: 'theirs', updatedAt: 't5' }))

    expect(result.current.document.text).toBe('theirs')
    expect(result.current.saveState).toBe('clean')
    await elapse(AUTOSAVE_DELAY_MS * 2)
    expect(save).not.toHaveBeenCalled()
  })

  it('sends unsaved work when the editor is left before the debounce fires', async () => {
    const { save, calls } = controllableSave()
    const { result, unmount } = setup(save)

    act(() => result.current.change(type('typed, then navigated away')))
    unmount()

    expect(save).toHaveBeenCalledTimes(1)
    expect(calls[0].sent.text).toBe('typed, then navigated away')
  })

  it('sends nothing on the way out when there is nothing unsaved, or after a conflict', async () => {
    const clean = controllableSave()
    setup(clean.save).unmount()
    expect(clean.save).not.toHaveBeenCalled()

    const refused = controllableSave()
    const { result, unmount } = setup(refused.save)
    act(() => result.current.change(type('mine')))
    await elapse(AUTOSAVE_DELAY_MS)
    await act(async () => refused.calls[0].reject(new ApiError('conflict', 'Taken.', 409)))
    unmount()

    expect(refused.save).toHaveBeenCalledTimes(1)
  })

  it('warns before the tab is closed only while something is unsaved', async () => {
    const { save, calls } = controllableSave()
    const { result } = setup(save)

    const unload = () => {
      const event = new Event('beforeunload', { cancelable: true })
      window.dispatchEvent(event)
      return event.defaultPrevented
    }

    expect(unload()).toBe(false)
    act(() => result.current.change(type('unsaved')))
    expect(unload()).toBe(true)

    /* Sent is not saved: the request can still be lost with the page. */
    await elapse(AUTOSAVE_DELAY_MS)
    expect(unload()).toBe(true)

    await act(async () => calls[0].resolve({ ...calls[0].sent, updatedAt: 't1' }))
    expect(unload()).toBe(false)
  })
})

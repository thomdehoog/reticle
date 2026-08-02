import { act, render } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AUTOSAVE_MAX_WAIT_MS, AUTOSAVE_PAUSE_MS, useAutosave } from './useAutosave'

function Editor({
  snapshot,
  isDirty,
  save,
}: {
  snapshot: unknown
  isDirty: () => boolean
  save: () => void
}) {
  useAutosave({ snapshot, isDirty, save })
  return null
}

describe('useAutosave', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('saves once the author stops typing', () => {
    const save = vi.fn()
    render(<Editor snapshot={{ title: 'Confocal' }} isDirty={() => true} save={save} />)

    act(() => void vi.advanceTimersByTime(AUTOSAVE_PAUSE_MS))
    expect(save).toHaveBeenCalledTimes(1)
  })

  /**
   * The one that matters. Publishing, unpublishing and archiving all take the
   * work first — they clear the dirty flag, then await their own request. A
   * timer that fired anyway would send a second write carrying the same
   * `expectedUpdatedAt`, which the server answers with a conflict; the author
   * is working alone and is told a colleague edited their guide.
   */
  it('asks again whether there is anything to save before it fires', () => {
    let dirty = true
    const save = vi.fn()
    render(<Editor snapshot={{ title: 'Confocal' }} isDirty={() => dirty} save={save} />)

    dirty = false
    act(() => void vi.advanceTimersByTime(AUTOSAVE_MAX_WAIT_MS))

    expect(save).not.toHaveBeenCalled()
  })

  it('stops waiting for a pause that never comes', () => {
    const save = vi.fn()
    const { rerender } = render(<Editor snapshot={0} isDirty={() => true} save={save} />)

    /* An author dictating a procedure keeps typing, so every keystroke restarts
       the pause timer. Only the ceiling gets the work to the server. */
    for (let keystroke = 1; keystroke * 200 <= AUTOSAVE_MAX_WAIT_MS; keystroke += 1) {
      rerender(<Editor snapshot={keystroke} isDirty={() => true} save={save} />)
      act(() => void vi.advanceTimersByTime(200))
    }

    expect(save).toHaveBeenCalled()
  })

  it('saves what is unsaved when the editor closes', () => {
    const save = vi.fn()
    const { unmount } = render(<Editor snapshot={{}} isDirty={() => true} save={save} />)

    unmount()
    expect(save).toHaveBeenCalledTimes(1)
  })

  it('does not save on close when there is nothing to save', () => {
    const save = vi.fn()
    const { unmount } = render(<Editor snapshot={{}} isDirty={() => false} save={save} />)

    unmount()
    expect(save).not.toHaveBeenCalled()
  })
})

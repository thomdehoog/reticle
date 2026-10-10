/**
 * Adversarial probes against tag entry.
 *
 * Tags are the navigation, so the failure that matters is not a crash: it is
 * two tags for one concept, which silently splits a facility's vocabulary.
 */

import { fireEvent, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { TagInput, slugifyTag } from './TagInput'
import { renderWithApp } from '../../test/harness'
import { MAX_TAGS_PER_GUIDE, type Tag } from '../../domain/types'

function tagServer(tags: Tag[] = []) {
  const fetchImpl = vi.fn(async (input: string | URL | Request) => {
    const path = new URL(String(input), 'http://reticle.test').pathname
    const body = path === '/api/tags' ? tags : { id: 'u1', role: 'admin' }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }) as unknown as typeof fetch
  return fetchImpl
}

function renderTagInput(tags: string[] = []) {
  const onChange = vi.fn()
  const view = renderWithApp(<TagInput tags={tags} onChange={onChange} />, {
    fetchImpl: tagServer([
      { id: 't1', slug: 'confocal', name: 'Confocal', guideCount: 4 },
      { id: 't2', slug: 'stellaris', name: 'Stellaris', guideCount: 2 },
    ]),
  })
  return { ...view, onChange, field: screen.getByLabelText('Add a tag') as HTMLInputElement }
}

/**
 * The character-for-character agreement with the server is pinned in
 * src/domain/slug.test.ts, against the case file the backend suite also reads.
 * What is checked here is the part this component depends on.
 */
describe('slugifyTag — as the tag input uses it', () => {
  it('treats an accented word and its plain spelling as one tag', () => {
    expect(slugifyTag('Präparation')).toBe(slugifyTag('praeparation'))
    expect(slugifyTag('Köhler')).toBe('koehler')
  })

  it('handles a very long tag', () => {
    const long = `a${'b'.repeat(499)}`
    expect(slugifyTag(long)).toBe(long)
  })

  it('produces the empty string for input with nothing to slug', () => {
    for (const value of ['', '   ', '---', '!!!', '🔬', '顕微鏡', '​']) {
      expect(slugifyTag(value)).toBe('')
    }
  })
})

describe('TagInput — hostile entry', () => {
  /** Types a value and presses Enter, the way the field is actually committed. */
  function commit(field: HTMLInputElement, value: string) {
    fireEvent.change(field, { target: { value } })
    fireEvent.keyDown(field, { key: 'Enter', code: 'Enter' })
  }

  it('does not add a tag that slugifies to nothing', () => {
    const { onChange, field } = renderTagInput()

    for (const value of ['🔬', '顕微鏡', '!!!', '   ', '---']) commit(field, value)

    expect(onChange).not.toHaveBeenCalled()
  })

  /**
   * A tag with no letter or digit in it — an emoji, a CJK term such as 顕微鏡 —
   * cannot be stored. It must not simply vanish from the box: the text stays
   * where it can be corrected, and a sentence says what is wrong with it.
   */
  it('tells the author why a tag was refused', () => {
    const { field } = renderTagInput()

    commit(field, '顕微鏡')

    expect(field.value).toBe('顕微鏡')
    expect(screen.getByRole('alert')).toHaveTextContent(/A tag needs at least one letter or digit/)
  })

  it('folds duplicates that differ only in case, spacing or punctuation', () => {
    const { onChange, field } = renderTagInput(['live-cell'])

    for (const spelling of ['Live Cell', 'LIVE-CELL', '  live   cell  ', '--live-cell--']) {
      commit(field, spelling)
    }

    expect(onChange).not.toHaveBeenCalled()
  })

  it('removes one tag per Backspace and never more', async () => {
    const user = userEvent.setup()
    const { onChange, field } = renderTagInput(['a', 'b'])

    await user.click(field)
    for (let i = 0; i < 6; i += 1) await user.keyboard('{Backspace}')

    // The component is controlled and this harness never feeds the new value
    // back, so every press acts on the same two tags. What matters is that it
    // never throws and never takes more than one tag per press.
    expect(onChange).toHaveBeenCalledWith(['a'])
    for (const call of onChange.mock.calls) expect(call[0]).toHaveLength(1)
  })

  it('commits a half-typed tag when the field loses focus', async () => {
    const user = userEvent.setup()
    const { onChange, field } = renderTagInput()

    await user.click(field)
    fireEvent.change(field, { target: { value: 'stell' } })
    await user.tab()

    expect(onChange).toHaveBeenCalledWith(['stell'])
  })

  /**
   * The server refuses a tag longer than 60 characters, and with it the whole
   * save. Refusing it here, in words, is what keeps one overlong tag from
   * turning every later autosave into a `validation_failed`.
   */
  it('refuses a tag longer than the server accepts, and says so', () => {
    const { onChange, field } = renderTagInput()

    commit(field, 'x'.repeat(61))

    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('at most 60 characters')

    commit(field, 'x'.repeat(60))
    expect(onChange).toHaveBeenCalledWith(['x'.repeat(60)])
  })

  /** Likewise the number of tags: the server's ceiling is MAX_TAGS_PER_GUIDE. */
  it('stops the author from adding more tags than the server accepts', () => {
    const existing = Array.from({ length: MAX_TAGS_PER_GUIDE }, (_, i) => `tag-${i}`)
    const { onChange, field } = renderTagInput(existing)

    commit(field, 'one-too-many')

    expect(onChange).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(`at most ${MAX_TAGS_PER_GUIDE} tags`)
  })
})

describe('TagInput — reusing the vocabulary', () => {
  const KNOWN: Tag[] = [
    { id: 't1', slug: 'confocal', name: 'Confocal', guideCount: 4 },
    { id: 't2', slug: 'stellaris', name: 'Stellaris', guideCount: 2 },
    { id: 't3', slug: 'las-x', name: 'LAS X', guideCount: 7 },
  ]

  function renderWith(props: Partial<Parameters<typeof TagInput>[0]> = {}) {
    const onChange = vi.fn()
    renderWithApp(<TagInput tags={[]} onChange={onChange} {...props} />, {
      fetchImpl: tagServer(KNOWN),
    })
    return { onChange, field: screen.getByRole('combobox', { name: 'Add a tag' }) }
  }

  it('suggests existing tags by name as well as by slug', async () => {
    const user = userEvent.setup()
    const { field } = renderWith()

    await user.type(field, 'las x')

    const option = await screen.findByRole('option', { name: /LAS X/ })
    expect(option).toHaveTextContent('7 guides')
    expect(field).toHaveAttribute('aria-expanded', 'true')
  })

  it('offers the existing tag when a longer variant of it is typed', async () => {
    const user = userEvent.setup()
    const { field } = renderWith()

    await user.type(field, 'Stellaris-5')

    expect(await screen.findByRole('option', { name: /Stellaris/ })).toBeInTheDocument()
    expect(screen.getByText(/Enter adds “Stellaris-5” as a new tag/)).toBeInTheDocument()
  })

  it('adds the highlighted suggestion with the keyboard alone', async () => {
    const user = userEvent.setup()
    const { field, onChange } = renderWith()

    await user.type(field, 'Stellaris-5')
    await screen.findByRole('option', { name: /Stellaris/ })
    await user.keyboard('{ArrowDown}')
    expect(field).toHaveAttribute('aria-activedescendant', screen.getByRole('option').id)
    await user.keyboard('{Enter}')

    expect(onChange).toHaveBeenCalledWith(['stellaris'])
  })

  it('adds what was typed when nothing is highlighted', async () => {
    const user = userEvent.setup()
    const { field, onChange } = renderWith()

    await user.type(field, 'Stellaris-5')
    await screen.findByRole('option', { name: /Stellaris/ })
    await user.keyboard('{Enter}')

    expect(onChange).toHaveBeenCalledWith(['stellaris-5'])
  })

  it('closes the suggestions on Escape without adding anything', async () => {
    const user = userEvent.setup()
    const { field, onChange } = renderWith()

    await user.type(field, 'conf')
    await screen.findByRole('option', { name: /Confocal/ })
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('option')).not.toBeInTheDocument()
    expect(field).toHaveValue('conf')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('adds a suggestion on click, not the half-typed text', async () => {
    const user = userEvent.setup()
    const { field, onChange } = renderWith()

    await user.type(field, 'conf')
    await user.click(await screen.findByRole('option', { name: /Confocal/ }))

    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(['confocal'])
  })

  it('does not suggest a tag the guide already carries', async () => {
    const user = userEvent.setup()
    const { field } = renderWith({ tags: ['confocal'] })

    await user.type(field, 'conf')

    await waitFor(() => expect(field).toHaveAttribute('aria-expanded', 'false'))
    expect(screen.queryByRole('option')).not.toBeInTheDocument()
  })

  /* The server names a new tag after the first spelling it is sent, so the
     guide editor sends the author's — and an existing tag's slug, never a
     respelling of it. */
  it('keeps the spelling of a new tag when asked to, and reuses an existing slug', async () => {
    const user = userEvent.setup()
    const { field, onChange } = renderWith({ spelling: 'as-typed' })

    await user.type(field, 'Live  Cell{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['Live Cell'])

    await user.type(field, 'LAS X')
    await screen.findByRole('option', { name: /LAS X/ })
    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['las-x'])
  })

  it('shows a known tag under its display name and marks a new one', async () => {
    renderWith({ tags: ['las-x', 'Brand New'] })

    expect(await screen.findByText('LAS X')).toBeInTheDocument()
    expect(screen.getByText('Brand New').closest('.tag')).toHaveClass('tag--new')
    expect(screen.getByText('LAS X').closest('.tag')).not.toHaveClass('tag--new')
    expect(screen.getByRole('button', { name: 'Remove tag LAS X' })).toBeInTheDocument()
  })
})

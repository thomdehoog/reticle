import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { createStep } from '../../domain/guide'
import type { Step } from '../../domain/types'
import { StepEditor } from './StepEditor'

/**
 * The step card is the surface an author spends the whole of their time on,
 * and it had no test file of its own — every assertion about it came in
 * sideways through the whole editor page, where a card's own behaviour is hard
 * to see and easy to leave uncovered. These cover what the card itself
 * promises: what its controls are called, where its title sits, and when each
 * button is allowed to do anything.
 */

function renderCard(step: Step, props: Partial<Parameters<typeof StepEditor>[0]> = {}) {
  const onChange = vi.fn()
  const onMove = vi.fn()
  const onRemove = vi.fn()
  render(
    <StepEditor
      step={step}
      number={step.kind === 'step' ? 1 : null}
      isFirst={false}
      isLast={false}
      canRemove
      focusBulletId={null}
      uploading={false}
      onChange={onChange}
      onRemove={onRemove}
      onMove={onMove}
      onFocusBullet={vi.fn()}
      onUpload={vi.fn()}
      onDragStart={vi.fn()}
      onDragEnter={vi.fn()}
      onDragEnd={vi.fn()}
      dragging={false}
      dropTarget={false}
      {...props}
    />,
  )
  return { onChange, onMove, onRemove }
}

describe('StepEditor', () => {
  /**
   * The title shared the header row with a drag handle, a number, the kind
   * menu and three buttons, which left it 274px on a 1440px screen — and an
   * ordinary ZMB step title, "Book the system and check the room", needs 330.
   * The author could not see the end of the sentence they were typing. It is
   * the last child of the header so that it takes the whole of the next line,
   * and so that tabbing through the card visits the fields in the order they
   * are drawn.
   */
  it('gives the title a line of its own, after the controls', () => {
    renderCard(createStep({ title: 'Book the system and check the room' }))

    const head = document.querySelector('.editor-step__head')
    const title = document.querySelector('.editor-step__title-input')

    expect(head?.lastElementChild).toBe(title)
    expect(title).toHaveValue('Book the system and check the room')
  })

  it('keeps the three buttons together so they can be pushed to the end of the row', () => {
    renderCard(createStep())

    const actions = document.querySelector('.editor-step__actions')
    expect(actions?.querySelectorAll('button')).toHaveLength(3)
    /* Immediately before the title, which is what leaves the title the only
       thing on the second line. */
    expect(actions?.nextElementSibling).toBe(document.querySelector('.editor-step__title-input'))
  })

  /**
   * An Info or Pinned block carries no number on its card, in the outline, or
   * in the guide a reader opens. Announcing its buttons as "step 3" would
   * invent a fourth answer to which step this is.
   */
  it('names its controls after a numbered step', () => {
    renderCard(createStep({ kind: 'step' }), { number: 3 })

    expect(screen.getByRole('button', { name: 'Reorder step 3' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move step 3 up' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Move step 3 down' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete step 3' })).toBeInTheDocument()
  })

  it('does not call an unnumbered block a step', () => {
    renderCard(createStep({ kind: 'info' }), { number: null })

    expect(screen.getByRole('button', { name: 'Reorder this block' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete this block' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /step/i })).toBeNull()
    expect(document.querySelector('.editor-step__number')?.textContent).toBe('—')
  })

  it('offers no number in the placeholder of a block that has none', () => {
    renderCard(createStep({ kind: 'pinned' }), { number: null })

    expect(screen.getByPlaceholderText('Title (optional)')).toBeInTheDocument()
  })

  it('reports a retyped title', async () => {
    const user = userEvent.setup()
    const { onChange } = renderCard(createStep({ title: '' }), { number: 2 })

    await user.type(screen.getByPlaceholderText('Step 2 title (optional)'), 'Shut down')

    expect(onChange).toHaveBeenCalled()
    /* Controlled and never re-rendered by this test, so each keystroke reports
       the same empty starting value plus one character — the last is enough to
       show the change reaches the caller. */
    expect(onChange.mock.calls.at(-1)?.[0]).toMatchObject({ title: 'n' })
  })

  it('turns a step into an info block', async () => {
    const user = userEvent.setup()
    const { onChange } = renderCard(createStep({ kind: 'step' }))

    await user.selectOptions(screen.getByLabelText('What this block is'), 'info')

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ kind: 'info' }))
  })

  it('will not move the first block up or the last one down', () => {
    renderCard(createStep(), { number: 1, isFirst: true, isLast: true })

    expect(screen.getByRole('button', { name: 'Move step 1 up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move step 1 down' })).toBeDisabled()
  })

  /** A guide with no blocks at all has nothing to publish, so the last one stays. */
  it('will not delete the only block in the guide', () => {
    renderCard(createStep(), { number: 1, canRemove: false })

    expect(screen.getByRole('button', { name: 'Delete step 1' })).toBeDisabled()
  })

  it('moves in the direction the button says', async () => {
    const user = userEvent.setup()
    const { onMove } = renderCard(createStep(), { number: 1 })

    await user.click(screen.getByRole('button', { name: 'Move step 1 down' }))
    expect(onMove).toHaveBeenCalledWith(1)

    await user.click(screen.getByRole('button', { name: 'Move step 1 up' }))
    expect(onMove).toHaveBeenCalledWith(-1)
  })
})

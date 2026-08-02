/**
 * The dialog's keyboard behaviour.
 *
 * `aria-modal` says the page behind is inert but changes nothing about the Tab
 * order, so a dialog that does not catch Tab lets the keyboard walk out into
 * the form underneath while the author is still looking at the dialog. In the
 * annotation editor that is not cosmetic: the next field out is the alt-text
 * box behind it, and a keystroke aimed at the dialog lands in a text box the
 * author cannot see.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { Modal } from './ui'

function Fixture() {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Annotate image
      </button>
      <input aria-label="Description of image 1" />
      {open && (
        <Modal title="Annotate image" onClose={() => setOpen(false)}>
          <input aria-label="Shape colour" />
        </Modal>
      )}
    </>
  )
}

describe('Modal', () => {
  it('keeps Tab inside the dialog', async () => {
    const user = userEvent.setup()
    render(<Fixture />)

    await user.click(screen.getByRole('button', { name: 'Annotate image' }))

    const behind = screen.getByLabelText('Description of image 1')
    const inside = screen.getByLabelText('Shape colour')
    const close = screen.getByRole('button', { name: 'Close' })

    expect(close).toHaveFocus()
    await user.tab()
    expect(inside).toHaveFocus()
    await user.tab()
    expect(close).toHaveFocus()
    expect(behind).not.toHaveFocus()
  })

  it('wraps backwards rather than reversing out of the dialog', async () => {
    const user = userEvent.setup()
    render(<Fixture />)

    await user.click(screen.getByRole('button', { name: 'Annotate image' }))
    await user.tab({ shift: true })

    expect(screen.getByLabelText('Shape colour')).toHaveFocus()
  })

  it('hands focus back to whatever opened it', async () => {
    const user = userEvent.setup()
    render(<Fixture />)

    const opener = screen.getByRole('button', { name: 'Annotate image' })
    await user.click(opener)
    await user.keyboard('{Escape}')

    expect(opener).toHaveFocus()
  })
})

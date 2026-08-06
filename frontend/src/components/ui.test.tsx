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

/**
 * A dialog whose field is driven by the state of whatever opened it, and whose
 * `onClose` is written the way every caller writes it — inline.
 *
 * That combination is what broke: a new `onClose` on every keystroke re-ran the
 * dialog's focus effect, and its cleanup hands focus back to the opener, so the
 * caret left the field after the first character. The password confirming a
 * section's deletion reached the server as the letter "c".
 */
function TypingFixture() {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <p>Sent: {text}</p>
      {open && (
        <Modal title="Confirm" onClose={() => setOpen(false)}>
          <label htmlFor="secret">Your password</label>
          <input
            id="secret"
            type="password"
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </Modal>
      )}
    </>
  )
}

describe('Modal', () => {
  it('keeps the caret in a field the opener holds the state for', async () => {
    const user = userEvent.setup()
    render(<TypingFixture />)

    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.type(screen.getByLabelText('Your password'), 'correct-horse-battery')

    expect(screen.getByLabelText('Your password')).toHaveValue('correct-horse-battery')
    expect(screen.getByText('Sent: correct-horse-battery')).toBeInTheDocument()
  })

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

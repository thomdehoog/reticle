import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { Modal } from './ui'

function Opener({ onClose }: { onClose?: () => void }) {
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState('')
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <button type="button">Elsewhere</button>
      {open && (
        <Modal
          title="New thing"
          /* A new function every render, as real callers pass. */
          onClose={() => {
            onClose?.()
            setOpen(false)
          }}
        >
          <label>
            Name
            <input value={typed} onChange={(event) => setTyped(event.target.value)} />
          </label>
          <label>
            Kind
            <select>
              <option>One</option>
              <option>Two</option>
            </select>
          </label>
          <button type="button">Create</button>
        </Modal>
      )}
    </>
  )
}

describe('Modal', () => {
  it('is a dialog named by its title', async () => {
    const user = userEvent.setup()
    render(<Opener />)

    await user.click(screen.getByRole('button', { name: 'Open' }))

    expect(screen.getByRole('dialog', { name: 'New thing' })).toHaveAttribute('aria-modal', 'true')
  })

  it('moves focus to its first field, not to its close button', async () => {
    const user = userEvent.setup()
    render(<Opener />)

    await user.click(screen.getByRole('button', { name: 'Open' }))

    expect(screen.getByLabelText('Name')).toHaveFocus()
  })

  it('leaves focus where the user put it when the caller re-renders', async () => {
    const user = userEvent.setup()
    render(<Opener />)

    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.type(screen.getByLabelText('Name'), 'abc')
    await user.selectOptions(screen.getByLabelText('Kind'), 'Two')

    expect(screen.getByLabelText('Name')).toHaveValue('abc')
    expect(screen.getByLabelText('Kind')).toHaveFocus()
  })

  it('keeps Tab inside the dialog, in both directions', async () => {
    const user = userEvent.setup()
    render(<Opener />)

    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.tab()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Create' })).toHaveFocus()

    /* Past the last stop comes the first — the close button — not the page behind. */
    await user.tab()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()

    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Create' })).toHaveFocus()
  })

  it('closes on Escape and gives focus back to what opened it', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<Opener onClose={onClose} />)

    const opener = screen.getByRole('button', { name: 'Open' })
    await user.click(opener)
    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes on a click outside the panel but not on one inside it', async () => {
    const user = userEvent.setup()
    render(<Opener />)

    await user.click(screen.getByRole('button', { name: 'Open' }))
    await user.click(screen.getByRole('heading', { name: 'New thing' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.click(document.querySelector('.modal-backdrop') as HTMLElement)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('lets only the dialog on top answer Escape', async () => {
    const closeOuter = vi.fn()
    const closeInner = vi.fn()
    const user = userEvent.setup()
    render(
      <Modal title="Outer" onClose={closeOuter}>
        <Modal title="Inner" onClose={closeInner}>
          <button type="button">Inside</button>
        </Modal>
      </Modal>,
    )

    await user.keyboard('{Escape}')

    expect(closeInner).toHaveBeenCalledTimes(1)
    expect(closeOuter).not.toHaveBeenCalled()
  })
})

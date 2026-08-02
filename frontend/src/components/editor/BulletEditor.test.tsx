/**
 * The keyboard contract of one editable bullet.
 *
 * An author writing a protocol should be able to type a whole step without
 * reaching for the mouse — and, just as importantly, should be able to leave
 * the field again. A textarea that swallows Tab in both directions is a trap
 * with no keyboard exit at all (WCAG 2.1.2 Level A), which means a guide cannot
 * be written without a mouse.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'

import { indentBullet } from '../../domain/guide'
import type { Bullet } from '../../domain/types'
import { BulletEditor } from './BulletEditor'

/** Real indent state, because the exits depend on where the indent has got to. */
function Harness() {
  const [bullet, setBullet] = useState<Bullet>({
    id: 'b1',
    text: 'Turn the key.',
    color: 'black',
    icon: null,
    level: 0,
  })

  return (
    <BulletEditor
      bullet={bullet}
      autoFocus={false}
      onChange={setBullet}
      onSplit={() => {}}
      onRemoveEmpty={() => {}}
      onIndent={(delta) => setBullet(indentBullet(bullet, delta))}
      onRemove={() => {}}
    />
  )
}

describe('BulletEditor keyboard', () => {
  it('indents with Tab while there is indent left to gain', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const text = screen.getByDisplayValue('Turn the key.')
    await user.click(text)
    await user.tab()
    expect(text).toHaveFocus()

    await user.tab()
    expect(text).toHaveFocus()
  })

  it('lets Tab out of the field once the indent is at its deepest', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const text = screen.getByDisplayValue('Turn the key.')
    await user.click(text)
    await user.tab()
    await user.tab()
    await user.tab()

    expect(text).not.toHaveFocus()
    expect(screen.getByLabelText('Outdent')).toHaveFocus()
  })

  it('lets Shift+Tab out of the field when there is nothing to outdent', async () => {
    const user = userEvent.setup()
    render(<Harness />)

    const text = screen.getByDisplayValue('Turn the key.')
    await user.click(text)
    await user.tab({ shift: true })

    expect(screen.getByLabelText('Bullet style')).toHaveFocus()
  })
})

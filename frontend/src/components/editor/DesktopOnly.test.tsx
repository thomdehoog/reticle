import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { DesktopOnly } from './DesktopOnly'

/**
 * jsdom has no layout and applies no media queries, so a test here cannot
 * observe which half is on screen — that is decided by one `@media` block in
 * the stylesheet, and `styles/app.test.ts` is what checks the block exists.
 *
 * What these do check is the contract that block relies on: both halves are
 * rendered, and they carry the two class names the stylesheet switches
 * between. Rendering the editor only above a width in JavaScript would need a
 * resize listener and a second copy of the breakpoint, and the two copies
 * would drift.
 */
describe('DesktopOnly', () => {
  it('renders the work and the note beside it, each labelled for the stylesheet', () => {
    render(
      <DesktopOnly what="a guide">
        <p>the editor</p>
      </DesktopOnly>,
    )

    expect(screen.getByText('the editor')).toBeInTheDocument()
    expect(document.querySelector('.desktop-only__work')).toContainElement(
      screen.getByText('the editor'),
    )
    expect(document.querySelector('.desktop-only')).not.toBeNull()
  })

  it('says what cannot be edited here, and why', () => {
    render(
      <DesktopOnly what="a wiki page">
        <p>the editor</p>
      </DesktopOnly>,
    )

    expect(screen.getByText(/Open this on a computer to edit a wiki page/)).toBeInTheDocument()
  })
})

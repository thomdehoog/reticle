/**
 * The banner shows one picture in two places, and the pair is the design.
 *
 * The plate is what a reader recognises the section by; the backdrop is what
 * gives the band the section's own colour. Either alone is a different and
 * worse banner — a plate on flat blue, or a photograph dimmed until it is a
 * texture — so what is held down here is that both are drawn, that they are
 * drawn from the same source, and that only one of them is offered to a screen
 * reader.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Banner } from './Banner'

function plate(): HTMLElement {
  const found = document.querySelector<HTMLElement>('.banner__plate')
  if (found === null) throw new Error('The banner drew no plate')
  return found
}

function backdrop(): HTMLElement {
  const found = document.querySelector<HTMLElement>('.banner__backdrop')
  if (found === null) throw new Error('The banner drew no backdrop')
  return found
}

describe('Banner', () => {
  it('is the page’s only h1, and says the section’s name in it', () => {
    render(<Banner title="Light Microscopy" />)

    expect(screen.getAllByRole('heading', { level: 1 })).toHaveLength(1)
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Light Microscopy')
  })

  it('shows the same photograph on the plate and behind it', () => {
    render(<Banner title="Light Microscopy" src="/api/media/m-cells" />)

    expect(plate().querySelector('img')).toHaveAttribute('src', '/api/media/m-cells')
    expect(backdrop().querySelector('img')).toHaveAttribute('src', '/api/media/m-cells')
  })

  /* The backdrop is the same picture a second time. Announced, it is the same
     section named twice by a screen reader that cannot see that one of them is
     out of focus — and the plate's own picture is already decorative, because
     the title beside it says what it is. */
  it('offers neither copy of the picture to a screen reader', () => {
    render(<Banner title="Light Microscopy" src="/api/media/m-cells" />)

    expect(backdrop()).toHaveAttribute('aria-hidden', 'true')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  /**
   * A section with no photograph yet still gets both, drawn from its name.
   *
   * This is the case the whole corpus is in until the migration brings the
   * pictures across, so it is the one most likely to be seen — and a backdrop
   * that fell back to flat colour while the plate fell back to artwork would
   * be two answers to one question.
   */
  it('draws both from the name when there is no photograph', () => {
    render(<Banner title="Electron Microscopy" />)

    expect(plate().querySelector('img')).toBeNull()
    expect(plate().querySelector('svg')).toBeInTheDocument()
    expect(backdrop().querySelector('svg')).toBeInTheDocument()
  })

  it('carries its introduction, and leaves the paragraph out when there is none', () => {
    const { unmount } = render(<Banner title="CryoEM" intro="Vitrification and screening." />)
    expect(screen.getByText('Vitrification and screening.')).toBeInTheDocument()
    unmount()

    render(<Banner title="CryoEM" />)
    expect(document.querySelector('.banner__intro')).toBeNull()
  })

  /* The heading comes before the introduction in the document, not merely above
     it on screen: the order a screen reader reads them in is the order they are
     written in, and CSS is what puts them beside the picture. */
  it('reads the title before the introduction', () => {
    render(<Banner title="CryoEM" intro="Vitrification and screening." />)

    const heading = screen.getByRole('heading', { level: 1 })
    const intro = screen.getByText('Vitrification and screening.')
    expect(heading.compareDocumentPosition(intro)).toBe(Node.DOCUMENT_POSITION_FOLLOWING)
  })

  /* The front page is the one moment worth a whole screen; two levels down the
     reader wants the guides. The stylesheet reads the modifier for the size. */
  it('marks the facility banner apart from a section’s', () => {
    const { unmount } = render(<Banner title="ZMB" variant="facility" />)
    expect(document.querySelector('.banner--facility')).toBeInTheDocument()
    unmount()

    render(<Banner title="CryoEM" />)
    expect(document.querySelector('.banner--section')).toBeInTheDocument()
  })
})

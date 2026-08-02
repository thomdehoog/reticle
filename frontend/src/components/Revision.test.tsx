/**
 * The rules about which date a document shows, pinned.
 *
 * Both of these have a wrong answer that looks right. Showing the edit date on
 * a published procedure makes a stable one look freshly changed, and a numeric
 * date is read as two different days depending on whether the reader is
 * thinking in English or in German.
 */

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Revision, formatDay } from './Revision'

describe('the revision stamp', () => {
  it('dates a published document by when it was published, not last edited', () => {
    render(
      <Revision
        version={7}
        publishedAt="2026-08-02T09:00:00Z"
        updatedAt="2026-11-30T09:00:00Z"
      />,
    )

    expect(screen.getByText('2 August 2026')).toBeInTheDocument()
    expect(screen.queryByText(/November/)).not.toBeInTheDocument()
    expect(screen.getByText(/v7/)).toBeInTheDocument()
  })

  it('dates a draft by its last edit, and says that is what it is', () => {
    render(<Revision version={3} publishedAt={null} updatedAt="2026-11-30T09:00:00Z" />)

    expect(screen.getByText(/edited/)).toBeInTheDocument()
    expect(screen.getByText('30 November 2026')).toBeInTheDocument()
  })

  it('carries the machine-readable instant alongside the words', () => {
    const { container } = render(
      <Revision version={1} publishedAt="2026-08-02T09:00:00Z" updatedAt="2026-08-02T09:00:00Z" />,
    )

    expect(container.querySelector('time')).toHaveAttribute(
      'datetime',
      '2026-08-02T09:00:00Z',
    )
  })

  it('spells the month out, so no date can be read as two different days', () => {
    /* 02/08 is 2 August to one half of this institute and 8 February to the
       other. There is no numeric format that both halves read the same way. */
    expect(formatDay('2026-08-02T09:00:00Z')).toBe('2 August 2026')
    expect(formatDay('2026-02-08T09:00:00Z')).toBe('8 February 2026')
  })
})

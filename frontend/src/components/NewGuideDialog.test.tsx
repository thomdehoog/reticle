/**
 * The category picker an author starts a guide from.
 *
 * One test, and it is the other half of a rule kept elsewhere: the browse
 * surfaces leave out a category with nothing published under it, and this is
 * where an author picks that category to put the first guide in it. If the
 * picker ever learns the browse rule, an empty category becomes one nobody can
 * fill, which is the point at which hiding it stops being cosmetic.
 */

import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { NewGuideDialog } from './NewGuideDialog'
import { categoryFixture, createFakeServer } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'

describe('NewGuideDialog', () => {
  it('offers the empty and hidden categories the front page leaves out', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-cryo', slug: 'cryoem', name: 'CryoEM' }),
        categoryFixture({ id: 'c-holding', slug: 'holding', name: 'Tag-only', isHidden: true }),
      ],
      guides: [],
    })
    renderWithApp(<NewGuideDialog onClose={() => {}} />, { fetchImpl: server.fetchImpl })

    const picker = await screen.findByLabelText('Category')
    expect(within(picker).getByRole('option', { name: 'CryoEM' })).toBeInTheDocument()
    expect(within(picker).getByRole('option', { name: 'Tag-only' })).toBeInTheDocument()
  })
})

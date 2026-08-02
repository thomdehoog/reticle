/**
 * What the rail offers, and what it must not.
 *
 * The rail and the phone drawer draw the same list from the same component, so
 * these cover both. The rule they exist for: the rail lists the places the
 * tiles list and no others. A category the front page has left out, offered
 * here, is the dead end back again under a shorter name.
 */

import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RailPlaces } from './SideRail'
import { categoryFixture, createFakeServer, guideFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'

function renderRail(server: ReturnType<typeof createFakeServer>, route = '/') {
  return renderWithApp(<RailPlaces />, { route, fetchImpl: server.fetchImpl })
}

describe('RailPlaces', () => {
  it('leaves out a category with nothing published under it', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy', orderIndex: 0 }),
        categoryFixture({ id: 'c-cryo', slug: 'cryoem', name: 'CryoEM', orderIndex: 1 }),
      ],
      guides: [guideFixture({ id: 'g1', categoryId: 'c-light', status: 'published' })],
    })
    renderRail(server)

    expect(await screen.findByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
    expect(screen.queryByRole('link', { name: 'CryoEM' })).not.toBeInTheDocument()
  })

  it('leaves an empty sub-category out of the level it lists', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-confocal',
          slug: 'confocal',
          name: 'Confocal',
          parentId: 'c-light',
          orderIndex: 0,
        }),
        categoryFixture({
          id: 'c-sted',
          slug: 'superresolution',
          name: 'Superresolution',
          parentId: 'c-light',
          orderIndex: 1,
        }),
      ],
      guides: [
        guideFixture({
          id: 'g-child',
          slug: 'stellaris-startup',
          categoryId: 'c-confocal',
          status: 'published',
        }),
      ],
    })
    renderRail(server, '/c/light-microscopy')

    expect(await screen.findByRole('heading', { name: 'Light Microscopy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Confocal' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Superresolution' })).not.toBeInTheDocument()
  })

  it('keeps a parent whose guides all sit in the categories under it', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-confocal',
          slug: 'confocal',
          name: 'Confocal',
          parentId: 'c-light',
          orderIndex: 0,
        }),
      ],
      guides: [
        guideFixture({
          id: 'g-child',
          slug: 'stellaris-startup',
          categoryId: 'c-confocal',
          status: 'published',
        }),
      ],
    })
    renderRail(server)

    expect(await screen.findByRole('link', { name: 'Light Microscopy' })).toBeInTheDocument()
  })
})

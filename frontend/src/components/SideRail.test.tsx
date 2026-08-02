/**
 * What the rail offers, and what it must not.
 *
 * The rail and the phone drawer draw the same list from the same component, so
 * these cover both. Two rules are being held down. The first: the rail lists the
 * places the tiles list and no others — a category the front page has left out,
 * offered here, is the dead end back again under a shorter name. The second: the
 * rail descends with the reader, one level at a time, all the way to the guides,
 * which is the whole reason there is no second list of them beside the guide.
 *
 * Both shapes a category can have are tested apart from each other, and so are
 * both routes to the bottom of the tree. A suite that only ever built
 * category → sub-category → guide would pass while a category that goes
 * straight to its guides — Electron Microscopy, at ZMB — listed the wrong thing
 * or nothing at all, and nobody would find out until a real corpus landed.
 */

import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { RailPlaces } from './SideRail'
import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  pageFixture,
} from '../test/fakeServer'
import { renderWithApp } from '../test/harness'

function renderRail(server: ReturnType<typeof createFakeServer>, route = '/') {
  return renderWithApp(<RailPlaces />, { route, fetchImpl: server.fetchImpl })
}

/** The rail's own list, so a heading link is not mistaken for a place in it. */
function places(): string[] {
  const list = document.querySelector('.rail__places')
  return [...(list?.querySelectorAll('.rail__item') ?? [])].map((item) =>
    (item.textContent ?? '').trim(),
  )
}

/**
 * Light Microscopy with two instruments under it, guides in one of them, and a
 * guide of the parent's own — the shape a rail has to get right at three
 * different depths.
 */
function nested() {
  return createFakeServer({
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
        id: 'c-widefield',
        slug: 'widefield',
        name: 'Widefield',
        parentId: 'c-light',
        orderIndex: 1,
      }),
    ],
    guides: [
      guideFixture({
        id: 'g-startup',
        slug: 'stellaris-startup',
        title: 'Stellaris start-up',
        categoryId: 'c-confocal',
        status: 'published',
      }),
      guideFixture({
        id: 'g-shutdown',
        slug: 'stellaris-shutdown',
        title: 'Stellaris shutdown',
        categoryId: 'c-confocal',
        status: 'published',
      }),
      guideFixture({
        id: 'g-widefield',
        slug: 'widefield-startup',
        title: 'Widefield start-up',
        categoryId: 'c-widefield',
        status: 'published',
      }),
      guideFixture({
        id: 'g-parents-own',
        slug: 'booking-a-system',
        title: 'Booking a system',
        categoryId: 'c-light',
        status: 'published',
      }),
    ],
  })
}

/**
 * Electron Microscopy: a top-level category with no sub-categories, holding its
 * guides and a wiki page directly. Nothing about this is a fallback — click it
 * and you are looking at guides.
 */
function flat() {
  return createFakeServer({
    categories: [categoryFixture({ id: 'c-em', slug: 'electron-microscopy', name: 'Electron Microscopy' })],
    guides: [
      guideFixture({
        id: 'g-grids',
        slug: 'preparing-grids',
        title: 'Preparing grids',
        categoryId: 'c-em',
        status: 'published',
      }),
      guideFixture({
        id: 'g-loading',
        slug: 'loading-the-holder',
        title: 'Loading the holder',
        categoryId: 'c-em',
        status: 'published',
      }),
    ],
    pages: [
      pageFixture({
        id: 'w-em',
        slug: 'electron-microscopy',
        title: 'Electron Microscopy',
        categoryId: 'c-em',
        isLanding: true,
        status: 'published',
      }),
      pageFixture({
        id: 'w-fixation',
        slug: 'fixation',
        title: 'Fixation protocols',
        categoryId: 'c-em',
        status: 'published',
      }),
    ],
  })
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

  /* Home, and everywhere else with no category behind it. */
  it('lists the browsable root categories at the front', async () => {
    renderRail(nested())

    expect(await screen.findByRole('heading', { name: 'Categories' })).toBeInTheDocument()
    expect(places()).toEqual(['Light Microscopy'])
  })

  it('lists the sub-categories of a category that has them, and none of its own guides', async () => {
    renderRail(nested(), '/c/light-microscopy')

    expect(await screen.findByRole('heading', { name: 'Light Microscopy' })).toBeInTheDocument()
    expect(places()).toEqual(['Confocal', 'Widefield'])
    /* Light Microscopy holds "Booking a system" itself. A category with children
       shows the children, and that guide is reached from its own page. */
    expect(screen.queryByRole('link', { name: 'Booking a system' })).not.toBeInTheDocument()
  })

  it('lists what a sub-category holds, with nothing marked', async () => {
    renderRail(nested(), '/c/confocal')

    expect(await screen.findByRole('link', { name: 'Stellaris start-up' })).toHaveAttribute(
      'href',
      '/g/stellaris-startup',
    )
    expect(places()).toEqual(['Stellaris start-up', 'Stellaris shutdown'])
    expect(document.querySelector('.rail__item--on')).toBeNull()
  })

  it('lists what a childless top-level category holds, with nothing marked', async () => {
    renderRail(flat(), '/c/electron-microscopy')

    expect(await screen.findByRole('link', { name: 'Preparing grids' })).toBeInTheDocument()
    /* The guides, then the wiki pages, in the order the category's page puts
       them — and not the landing page, which is that page. */
    expect(places()).toEqual(['Preparing grids', 'Loading the holder', 'Fixation protocols'])
    expect(document.querySelector('.rail__item--on')).toBeNull()
  })

  it('marks a guide read inside a sub-category, beside its neighbours', async () => {
    renderRail(nested(), '/g/stellaris-shutdown')

    const open = await screen.findByRole('link', { name: 'Stellaris shutdown' })
    expect(open).toHaveAttribute('aria-current', 'page')
    expect(places()).toEqual(['Stellaris start-up', 'Stellaris shutdown'])
    expect(screen.getByRole('link', { name: 'Stellaris start-up' })).not.toHaveAttribute(
      'aria-current',
    )
    /* The heading names the section and leads back to it: from a guide it is the
       only way to the section's own page that does not go through the front. */
    expect(
      within(screen.getByRole('heading', { name: 'Confocal' })).getByRole('link'),
    ).toHaveAttribute('href', '/c/confocal')
  })

  it('marks a guide read inside a childless top-level category', async () => {
    renderRail(flat(), '/g/loading-the-holder')

    const open = await screen.findByRole('link', { name: 'Loading the holder' })
    expect(open).toHaveAttribute('aria-current', 'page')
    expect(places()).toEqual(['Preparing grids', 'Loading the holder', 'Fixation protocols'])
  })

  it('marks a wiki page read inside a category, in the same list', async () => {
    renderRail(flat(), '/w/fixation')

    expect(await screen.findByRole('link', { name: 'Fixation protocols' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(places()).toEqual(['Preparing grids', 'Loading the holder', 'Fixation protocols'])
  })

  it('goes back to the front for a wiki page that belongs to no section', async () => {
    const server = flat()
    server.state.pages.push(
      pageFixture({ id: 'w-loose', slug: 'data-storage', title: 'Data storage', status: 'published' }),
    )
    renderRail(server, '/w/data-storage')

    expect(await screen.findByRole('heading', { name: 'Categories' })).toBeInTheDocument()
    expect(places()).toEqual(['Electron Microscopy'])
  })

  /**
   * The rail asking one category what it holds is the price of descending; the
   * same question asked of every category in the institute is not. On a corpus
   * with eighty sections that is eighty requests to draw one list.
   */
  it('asks only the category it is standing in what it holds', async () => {
    const server = nested()
    renderRail(server, '/c/confocal')
    await screen.findByRole('link', { name: 'Stellaris start-up' })

    const asked = server.requests.filter(
      (request) => request.method === 'GET' && /^\/(guides|pages)\?categoryId=/.test(request.path),
    )
    expect(asked.map((request) => request.path)).toEqual([
      '/guides?categoryId=c-confocal',
      '/pages?categoryId=c-confocal',
    ])
  })
})

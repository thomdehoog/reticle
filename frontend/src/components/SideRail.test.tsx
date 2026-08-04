/**
 * What the rail offers, and what it must not.
 *
 * The rail and the phone drawer draw the same two areas from the same
 * component, so these cover both. Three rules are being held down. The first:
 * the content area lists the places the tiles list and no others — a category
 * the front page has left out, offered here, is the dead end back again under a
 * shorter name. The second: that area descends with the reader, one level at a
 * time, all the way to the guides, which is the whole reason there is no second
 * list of them beside the guide. The third: the navigation area is the path
 * taken to get there, so it always begins at Home and always ends where the
 * reader is standing.
 *
 * Both shapes a category can have are tested apart from each other, and so are
 * both routes to the bottom of the tree. A suite that only ever built
 * category → sub-category → guide would pass while a category that goes
 * straight to its guides — Electron Microscopy, at ZMB — listed the wrong thing
 * or nothing at all, and nobody would find out until a real corpus landed.
 */

import { fireEvent, screen } from '@testing-library/react'
import { Link } from 'react-router'
import { describe, expect, it } from 'vitest'

import { RailGroups } from './SideRail'
import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  pageFixture,
} from '../test/fakeServer'
import { renderWithApp } from '../test/harness'

function renderRail(server: ReturnType<typeof createFakeServer>, route = '/') {
  return renderWithApp(<RailGroups />, { route, fetchImpl: server.fetchImpl })
}

function rowsOf(area: 'content' | 'trail'): string[] {
  const list = document.querySelector(`.rail__places--${area}`)
  return [...(list?.querySelectorAll('.rail__item') ?? [])].map((item) =>
    (item.textContent ?? '').trim(),
  )
}

/** What the content area lists, kept apart from the path above it. */
function places(): string[] {
  return rowsOf('content')
}

/** The path, from Home down to where the reader is standing. */
function trail(): string[] {
  return rowsOf('trail')
}

/**
 * The marked row of one area, or null.
 *
 * Asked of an area rather than of the document, because the two areas mark
 * different things and always did: the path marks the address in the bar, the
 * content marks the document being read, and on a guide only the second of
 * those exists. A search of the whole column cannot tell them apart.
 */
function marked(area: 'content' | 'trail'): string | null {
  const row = document.querySelector(`.rail__places--${area} .rail__item--on`)
  return row === null ? null : (row.textContent ?? '').trim()
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
        tags: ['stellaris'],
      }),
      guideFixture({
        id: 'g-shutdown',
        slug: 'stellaris-shutdown',
        title: 'Stellaris shutdown',
        categoryId: 'c-confocal',
        status: 'published',
        tags: ['stellaris'],
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
        tags: ['grids'],
      }),
      guideFixture({
        id: 'g-loading',
        slug: 'loading-the-holder',
        title: 'Loading the holder',
        categoryId: 'c-em',
        status: 'published',
        tags: ['grids'],
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

describe('RailGroups', () => {
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

    expect(await screen.findByRole('link', { name: 'Confocal' })).toBeInTheDocument()
    expect(trail()).toEqual(['Home', 'Light Microscopy'])
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
  it('lists the browsable root categories at the front, under a path of one', async () => {
    renderRail(nested())

    expect(await screen.findByRole('heading', { name: 'Content' })).toBeInTheDocument()
    expect(places()).toEqual(['Light Microscopy'])
    expect(trail()).toEqual(['Home'])
  })

  it('lists the sub-categories of a category that has them, and none of its own guides', async () => {
    renderRail(nested(), '/c/light-microscopy')

    expect(await screen.findByRole('heading', { name: 'Navigation' })).toBeInTheDocument()
    expect(places()).toEqual(['Confocal', 'Widefield'])
    /* Light Microscopy holds "Booking a system" itself. A category with children
       shows the children, and that guide is reached from its own page. */
    expect(screen.queryByRole('link', { name: 'Booking a system' })).not.toBeInTheDocument()
  })

  it('lists what a sub-category holds, under the path down to it', async () => {
    renderRail(nested(), '/c/confocal')

    expect(await screen.findByRole('link', { name: 'Stellaris' })).toHaveAttribute(
      'href',
      '/c/confocal#group-stellaris',
    )
    expect(places()).toEqual(['Stellaris'])
    /* Two levels, and the reader is standing on the second: the path is the
       only thing that says so, now that the heading is a fixed label. */
    expect(trail()).toEqual(['Home', 'Light Microscopy', 'Confocal'])
    expect(marked('trail')).toBe('Confocal')
    expect(marked('content')).toBeNull()
    expect(screen.getByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
  })

  /* The path is a path, not a list of siblings, and on a phone the padding it
     reads by is set in a second place. Both are asserted through the variable
     the two rules share rather than through a computed width, which jsdom does
     not have. */
  it('gives each step of the path its depth', async () => {
    renderRail(nested(), '/c/confocal')
    await screen.findByRole('link', { name: 'Stellaris' })

    const steps = [...document.querySelectorAll<HTMLElement>('.rail__item--step')]
    expect(steps.map((step) => step.style.getPropertyValue('--depth'))).toEqual(['0', '1', '2'])
  })

  /**
   * A category with nothing to list has no content area at all, rather than one
   * filled with the level above it.
   *
   * The shape is ZMB's, not a contrivance: a section whose guides all sit in a
   * holding category under it is browsable — the guides really are reachable
   * from it, by tag, through its own landing page — while having nothing of its
   * own and no child a reader may be sent to. The rail used to answer that by
   * listing the level above with the category marked, because the heading was
   * the only thing saying where the reader was and a blank column said nothing.
   * The path says it now, so listing a set of *siblings* under a heading
   * reading "Content" would be a second meaning for the word, appearing exactly
   * when there is nothing to show.
   */
  it('draws no content area for a category whose guides are all in a holding pen', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture(),
        categoryFixture({
          id: 'c-held',
          slug: 'confocal-hidden-guides',
          name: 'Confocal — hidden guides',
          parentId: 'c-light',
          isHidden: true,
        }),
      ],
      guides: [guideFixture({ id: 'g-held', categoryId: 'c-held', status: 'published' })],
    })
    renderRail(server, '/c/light-microscopy')

    expect(await screen.findByRole('heading', { name: 'Navigation' })).toBeInTheDocument()
    expect(trail()).toEqual(['Home', 'Light Microscopy'])
    expect(screen.queryByRole('heading', { name: 'Content' })).not.toBeInTheDocument()
    expect(places()).toEqual([])
  })

  it('lists a childless top-level category’s groups, not its guides', async () => {
    renderRail(flat(), '/c/electron-microscopy')

    /* The groups the page draws, in the order it draws them: the wiki articles
       first, then the tags. Not the documents — a ZMB section runs to a dozen
       procedures and a column of all of them is a list nobody reads to the end. */
    expect(await screen.findByRole('link', { name: 'Wikis' })).toBeInTheDocument()
    expect(places()).toEqual(['Wikis', 'Grids'])
    expect(marked('content')).toBeNull()
    expect(marked('trail')).toBe('Electron Microscopy')
  })

  it('points a group at that group on the section’s page', async () => {
    renderRail(flat(), '/c/electron-microscopy')

    /* Not at the tag's own page, which is the same group gathered from every
       section — a different set, and the wrong answer to "what is in here". */
    expect(await screen.findByRole('link', { name: 'Grids' })).toHaveAttribute(
      'href',
      '/c/electron-microscopy#group-grids',
    )
  })

  it('lists the same groups while a guide inside the section is open', async () => {
    renderRail(nested(), '/g/stellaris-shutdown')

    await screen.findByRole('link', { name: 'Stellaris' })
    expect(places()).toEqual(['Stellaris'])
    /* The path names the section and leads back to it: from a guide it is the
       only way to the section's own page that does not go through the front. */
    expect(trail()).toEqual(['Home', 'Light Microscopy', 'Confocal'])
    expect(screen.getByRole('link', { name: 'Confocal' })).toHaveAttribute('href', '/c/confocal')
  })

  /**
   * Nothing is marked while a document is open.
   *
   * A guide belongs to as many groups as it has tags, so marking the group it
   * is in would light up three rows at once and say the reader is in three
   * places. The path above already says where they are.
   */
  it('marks no group while a guide is being read', async () => {
    renderRail(flat(), '/g/loading-the-holder')

    await screen.findByRole('link', { name: 'Grids' })
    expect(marked('content')).toBeNull()
    expect(marked('trail')).toBeNull()
  })

  it('leaves an untagged guide out, because it is under no heading on the page', async () => {
    const server = createFakeServer({
      categories: [categoryFixture({ id: 'c-em', slug: 'electron-microscopy', name: 'EM' })],
      guides: [
        guideFixture({ id: 'g-1', slug: 'untagged', title: 'Untagged', categoryId: 'c-em', status: 'published' }),
        guideFixture({ id: 'g-2', slug: 'tagged', title: 'Tagged', categoryId: 'c-em', status: 'published', tags: ['grids'] }),
      ],
    })
    renderRail(server, '/c/electron-microscopy')

    expect(await screen.findByRole('link', { name: 'Grids' })).toBeInTheDocument()
    expect(places()).toEqual(['Grids'])
  })

  it('goes back to the front for a wiki page that belongs to no section', async () => {
    const server = flat()
    server.state.pages.push(
      pageFixture({ id: 'w-loose', slug: 'data-storage', title: 'Data storage', status: 'published' }),
    )
    renderRail(server, '/w/data-storage')

    expect(await screen.findByRole('heading', { name: 'Content' })).toBeInTheDocument()
    expect(places()).toEqual(['Electron Microscopy'])
    expect(trail()).toEqual(['Home'])
  })

  /**
   * The rail is furniture. It may fill in a moment later; it may not empty out
   * and refill on the way.
   *
   * Which category a guide belongs to is not in its address, so opening one
   * leaves the rail with the question outstanding for as long as the request
   * takes. Answering it with the front page's list for that moment is what made
   * the column jump from the section's guides to the institute's categories and
   * back on every click — and every click is what a reader working through a
   * set of procedures does. The section is held instead.
   *
   * The step out of the section's own page is the one that broke, so that is
   * the one taken here: standing on a category the rail has an answer in hand
   * saying the reader is on no document, and it is a stale answer the instant
   * they open one.
   *
   * Asserted on the render after the click and before anything is awaited,
   * because that render is the whole of the bug: let the requests settle first
   * and the wrong behaviour is invisible.
   */
  it('holds the section it is in while a guide inside it is on its way', async () => {
    const server = nested()
    renderWithApp(
      <>
        <Link to="/g/stellaris-shutdown">Open</Link>
        <RailGroups />
      </>,
      { route: '/c/confocal', fetchImpl: server.fetchImpl },
    )
    await screen.findByRole('link', { name: 'Stellaris' })

    fireEvent.click(screen.getByRole('link', { name: 'Open' }))
    expect(places()).toEqual(['Stellaris'])
  })

  /**
   * The rail asking one category what it holds is the price of descending; the
   * same question asked of every category in the institute is not. On a corpus
   * with eighty sections that is eighty requests to draw one list.
   */
  it('asks only the category it is standing in what it holds', async () => {
    const server = nested()
    renderRail(server, '/c/confocal')
    await screen.findByRole('link', { name: 'Stellaris' })

    const asked = server.requests.filter(
      (request) => request.method === 'GET' && /^\/(guides|pages)\?categoryId=/.test(request.path),
    )
    expect(asked.map((request) => request.path)).toEqual([
      '/guides?categoryId=c-confocal',
      '/pages?categoryId=c-confocal',
    ])
  })
})

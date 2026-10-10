import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { createFakeServer, guideFixture, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const VIEWER = userFixture({ id: 'u-vera', displayName: 'Vera Viewer', role: 'viewer' })

const published = (overrides: Parameters<typeof guideFixture>[0] = {}) =>
  guideFixture({ status: 'published', publishedAt: '2026-07-01T09:00:00Z', version: 1, ...overrides })

const GUIDES = [
  published({ id: 'g1', slug: 'one', tags: ['las-x', 'confocal'] }),
  published({ id: 'g2', slug: 'two', tags: ['confocal'] }),
  published({ id: 'g3', slug: 'three', tags: ['confocal', 'zen'] }),
  guideFixture({ id: 'g4', slug: 'four', tags: ['unfinished'] }),
]
const NAMES = { 'las-x': 'LAS X', confocal: 'Confocal', zen: 'ZEN' }

function tagNames(): string[] {
  return within(screen.getByRole('list')).getAllByRole('link').map((link) => link.textContent ?? '')
}

describe('TagsPage', () => {
  it('lists every tag by its display name with its guide count, linked to its guides', async () => {
    const server = createFakeServer({ user: VIEWER, guides: GUIDES, tagNames: NAMES })
    renderApp({ route: '/tags', server })

    const lasX = await screen.findByRole('link', { name: /LAS X/ })
    expect(lasX).toHaveAttribute('href', '/t/las-x')
    expect(lasX).toHaveTextContent('1 guide')
    expect(screen.getByRole('link', { name: /Confocal/ })).toHaveTextContent('3 guides')
    expect(screen.getByText('3 tags')).toBeInTheDocument()
    /* A tag only a draft carries does not exist as far as a viewer can tell. */
    expect(screen.queryByText('unfinished')).not.toBeInTheDocument()
  })

  it('narrows the list as the filter is typed, by name or by slug', async () => {
    const server = createFakeServer({ user: VIEWER, guides: GUIDES, tagNames: NAMES })
    const user = userEvent.setup()
    renderApp({ route: '/tags', server })

    await user.type(await screen.findByLabelText('Filter tags'), 'las-')

    expect(tagNames()).toEqual(['LAS X1 guide'])
    expect(screen.getByText('1 of 3 tags')).toBeInTheDocument()
  })

  it('says so when the filter matches nothing', async () => {
    const server = createFakeServer({ user: VIEWER, guides: GUIDES, tagNames: NAMES })
    const user = userEvent.setup()
    renderApp({ route: '/tags', server })

    await user.type(await screen.findByLabelText('Filter tags'), 'cryo')

    expect(screen.getByText('No tag matches “cryo”.')).toBeInTheDocument()
  })

  it('sorts alphabetically, or by how many guides carry each tag', async () => {
    const server = createFakeServer({ user: VIEWER, guides: GUIDES, tagNames: NAMES })
    const user = userEvent.setup()
    renderApp({ route: '/tags', server })

    await screen.findByRole('link', { name: /LAS X/ })
    expect(tagNames().map((text) => text.replace(/\d.*/, ''))).toEqual(['Confocal', 'LAS X', 'ZEN'])

    const byCount = screen.getByRole('button', { name: 'Most guides' })
    await user.click(byCount)

    expect(byCount).toHaveAttribute('aria-pressed', 'true')
    expect(tagNames()[0]).toContain('Confocal')
  })

  it('explains an empty index instead of showing a blank page', async () => {
    const server = createFakeServer({ user: VIEWER, guides: [] })
    renderApp({ route: '/tags', server })

    expect(await screen.findByText(/No tags yet/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Filter tags')).not.toBeInTheDocument()
  })

  it('is reachable from the header, and leads on to a tag and back', async () => {
    const server = createFakeServer({ user: VIEWER, guides: GUIDES, tagNames: NAMES })
    const user = userEvent.setup()
    const { location } = renderApp({ route: '/', server })

    const nav = await screen.findByRole('navigation', { name: 'Main' })
    await user.click(within(nav).getByRole('link', { name: 'Tags' }))
    expect(await screen.findByRole('heading', { name: 'Tags' })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Tags' })).toHaveAttribute('aria-current', 'page')

    await user.click(screen.getByRole('link', { name: /LAS X/ }))
    expect(await screen.findByRole('heading', { name: 'LAS X' })).toBeInTheDocument()
    expect(location()).toBe('/t/las-x')

    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    await user.click(within(crumbs).getByRole('link', { name: 'Tags' }))
    expect(location()).toBe('/tags')
  })
})

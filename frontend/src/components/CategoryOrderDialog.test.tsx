import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { categoryFixture, createFakeServer, userFixture } from '../test/fakeServer'
import { renderApp } from '../test/harness'

const AUTHOR = userFixture({ id: 'u-anna', displayName: 'Anna Author', role: 'author' })

const BASICS = categoryFixture({ id: 'c-basics', slug: 'basics', name: 'Basics', orderIndex: 0 })
const LIGHT = categoryFixture({ orderIndex: 1 })
const EM = categoryFixture({ id: 'c-em', slug: 'em', name: 'Electron Microscopy', orderIndex: 2 })
const CONFOCAL = categoryFixture({
  id: 'c-confocal',
  slug: 'confocal',
  name: 'Confocal',
  parentId: 'c-light',
  orderIndex: 0,
})
const HOLDING = categoryFixture({
  id: 'c-hold',
  slug: 'holding',
  name: 'Holding',
  isHidden: true,
  orderIndex: 3,
})

function cards(): string[] {
  return Array.from(document.querySelectorAll('.category-card__name')).map(
    (node) => node.textContent ?? '',
  )
}

function patches(server: ReturnType<typeof createFakeServer>) {
  return server.requests
    .filter((request) => request.method === 'PATCH')
    .map((request) => [request.path, request.body])
}

async function openDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Arrange categories' }))
  return screen.getByRole('dialog', { name: 'Arrange categories' })
}

describe('arranging categories', () => {
  it('moves a category up, saving only the rows that changed place', async () => {
    const server = createFakeServer({ categories: [BASICS, LIGHT, EM] })
    const user = userEvent.setup()
    renderApp({ server })

    const dialog = await openDialog(user)
    await user.click(within(dialog).getByRole('button', { name: 'Move Electron Microscopy up' }))

    await waitFor(() => expect(cards()).toEqual(['Basics', 'Electron Microscopy', 'Light Microscopy']))
    expect(patches(server)).toEqual([
      ['/categories/c-em', { orderIndex: 1 }],
      ['/categories/c-light', { orderIndex: 2 }],
    ])
    expect(within(dialog).getByRole('status')).toHaveTextContent('Moved Electron Microscopy up.')
  })

  it('moves a category down, and cannot move one past either end', async () => {
    const server = createFakeServer({ categories: [BASICS, LIGHT, EM] })
    const user = userEvent.setup()
    renderApp({ server })

    const dialog = await openDialog(user)
    expect(within(dialog).getByRole('button', { name: 'Move Basics up' })).toBeDisabled()
    expect(within(dialog).getByRole('button', { name: 'Move Electron Microscopy down' })).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: 'Move Basics down' }))

    await waitFor(() => expect(cards()).toEqual(['Light Microscopy', 'Basics', 'Electron Microscopy']))
  })

  it('keeps focus on the button, so it can be pressed again', async () => {
    const server = createFakeServer({ categories: [BASICS, LIGHT, EM] })
    const user = userEvent.setup()
    renderApp({ server })

    const dialog = await openDialog(user)
    const up = within(dialog).getByRole('button', { name: 'Move Electron Microscopy up' })
    await user.click(up)
    await waitFor(() => expect(cards()[1]).toBe('Electron Microscopy'))
    expect(up).toHaveFocus()

    await user.keyboard('{Enter}')
    await waitFor(() => expect(cards()[0]).toBe('Electron Microscopy'))
  })

  it('moves a sub-category among its own siblings only, and lists hidden categories', async () => {
    const second = categoryFixture({
      id: 'c-wide',
      slug: 'widefield',
      name: 'Widefield',
      parentId: 'c-light',
      orderIndex: 1,
    })
    const server = createFakeServer({ categories: [BASICS, LIGHT, CONFOCAL, second, HOLDING] })
    const user = userEvent.setup()
    renderApp({ server })

    const dialog = await openDialog(user)
    expect(within(dialog).getByText('(hidden)')).toBeInTheDocument()
    /* First among its siblings, although it is far from first in the list. */
    expect(within(dialog).getByRole('button', { name: 'Move Confocal up' })).toBeDisabled()

    await user.click(within(dialog).getByRole('button', { name: 'Move Widefield up' }))

    await waitFor(() =>
      expect(patches(server)).toEqual([
        ['/categories/c-wide', { orderIndex: 0 }],
        ['/categories/c-confocal', { orderIndex: 1 }],
      ]),
    )
  })

  it('reports a refused move and shows the order the server still holds', async () => {
    const server = createFakeServer({ categories: [BASICS, LIGHT, EM] })
    const user = userEvent.setup()
    renderApp({ server })

    const dialog = await openDialog(user)
    /* The session's role changes underneath the open dialog. */
    server.state.user = { ...server.state.user, role: 'author' }
    await user.click(within(dialog).getByRole('button', { name: 'Move Electron Microscopy up' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('You are not allowed to do that.')
    expect(cards()).toEqual(['Basics', 'Light Microscopy', 'Electron Microscopy'])
  })

  it('is an admin\'s tool: an author is not offered it', async () => {
    const server = createFakeServer({ user: AUTHOR, categories: [BASICS, LIGHT] })
    renderApp({ server })

    await screen.findByRole('heading', { name: 'Guides' })
    expect(screen.queryByRole('button', { name: 'Arrange categories' })).not.toBeInTheDocument()
  })
})

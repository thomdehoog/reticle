import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { categoryFixture, createFakeServer, guideFixture, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { CategoriesPage } from './CategoriesPage'

function renderCategories(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/categories" element={<CategoriesPage />} />
    </Routes>,
    { route: '/categories', fetchImpl: server.fetchImpl },
  )
}

function twoCategories() {
  return [
    categoryFixture({ id: 'c-light', slug: 'light', name: 'Light Microscopy', orderIndex: 0 }),
    categoryFixture({ id: 'c-em', slug: 'em', name: 'Electron Microscopy', orderIndex: 1 }),
  ]
}

describe('CategoriesPage', () => {
  it('lists hidden categories too, since this is where they get un-hidden', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy' }),
        categoryFixture({ id: 'c-holding', slug: 'holding', name: 'Tag-only', isHidden: true }),
      ],
      guides: [],
    })
    renderCategories(server)

    expect(await screen.findByRole('link', { name: 'Light Microscopy' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Tag-only' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Hidden — show it' })).toBeInTheDocument()
  })

  it('creates a category', async () => {
    const server = createFakeServer({ categories: twoCategories(), guides: [] })
    const user = userEvent.setup()
    renderCategories(server)

    await user.click(await screen.findByRole('button', { name: /New category/ }))
    await user.type(screen.getByLabelText('Name'), 'Sample Preparation')
    await user.type(screen.getByLabelText('Description'), 'Fixing, staining, mounting.')
    await user.click(screen.getByRole('button', { name: 'Create category' }))

    await waitFor(() => expect(server.state.categories).toHaveLength(3))
    const created = server.state.categories[2]
    expect(created.name).toBe('Sample Preparation')
    expect(created.description).toBe('Fixing, staining, mounting.')
    expect(created.parentId).toBeNull()
  })

  it('renames and re-parents a category', async () => {
    const server = createFakeServer({ categories: twoCategories(), guides: [] })
    const user = userEvent.setup()
    renderCategories(server)

    const row = (await screen.findByRole('link', { name: 'Electron Microscopy' })).closest('tr')
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Edit' }))

    const name = screen.getByLabelText('Name')
    await user.clear(name)
    await user.type(name, 'Electron microscopy')
    await user.selectOptions(screen.getByLabelText('Sits under'), 'c-light')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => {
      const updated = server.state.categories.find((c) => c.id === 'c-em')
      expect(updated?.name).toBe('Electron microscopy')
      expect(updated?.parentId).toBe('c-light')
    })
  })

  /* Moving a category inside itself detaches the whole branch, and every guide
     underneath it stops being reachable by browsing. */
  it('will not offer a category itself, or its own children, as a parent', async () => {
    const server = createFakeServer({
      categories: [
        categoryFixture({ id: 'c-light', name: 'Light Microscopy', orderIndex: 0 }),
        categoryFixture({
          id: 'c-confocal',
          slug: 'confocal',
          name: 'Confocal',
          parentId: 'c-light',
          orderIndex: 0,
        }),
      ],
      guides: [],
    })
    const user = userEvent.setup()
    renderCategories(server)

    const row = (await screen.findByRole('link', { name: 'Light Microscopy' })).closest('tr')
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Edit' }))

    const parent = screen.getByLabelText('Sits under') as HTMLSelectElement
    const options = [...parent.options].map((option) => option.textContent)
    expect(options).not.toContain('Light Microscopy')
    expect(options).not.toContain('Confocal')
  })

  it('toggles a category out of the browse tree and back', async () => {
    const server = createFakeServer({ categories: twoCategories(), guides: [] })
    const user = userEvent.setup()
    renderCategories(server)

    const row = (await screen.findByRole('link', { name: 'Light Microscopy' })).closest('tr')
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Visible — hide it' }))

    await waitFor(() =>
      expect(server.state.categories.find((c) => c.id === 'c-light')?.isHidden).toBe(true),
    )
    expect(await screen.findByRole('button', { name: 'Hidden — show it' })).toBeInTheDocument()
  })

  it('swaps two siblings when one is nudged up', async () => {
    const server = createFakeServer({ categories: twoCategories(), guides: [] })
    const user = userEvent.setup()
    renderCategories(server)

    await user.click(
      await screen.findByRole('button', { name: 'Move Electron Microscopy up' }),
    )

    await waitFor(() => {
      expect(server.state.categories.find((c) => c.id === 'c-em')?.orderIndex).toBe(0)
      expect(server.state.categories.find((c) => c.id === 'c-light')?.orderIndex).toBe(1)
    })
  })

  it('deletes an empty category once the admin confirms', async () => {
    const server = createFakeServer({ categories: twoCategories(), guides: [] })
    const user = userEvent.setup()
    renderCategories(server)

    await user.click(await screen.findByRole('button', { name: 'Delete Electron Microscopy' }))
    await user.click(screen.getByRole('button', { name: 'Delete category' }))

    await waitFor(() => expect(server.state.categories).toHaveLength(1))
    expect(server.state.categories[0].id).toBe('c-light')
  })

  it('repeats the server’s reason when the category still holds guides', async () => {
    const server = createFakeServer({
      categories: twoCategories(),
      guides: [guideFixture({ categoryId: 'c-em' })],
    })
    const user = userEvent.setup()
    renderCategories(server)

    await user.click(await screen.findByRole('button', { name: 'Delete Electron Microscopy' }))
    await user.click(screen.getByRole('button', { name: 'Delete category' }))

    expect(
      await screen.findByText('Move the guides in this category somewhere else first.'),
    ).toBeInTheDocument()
    expect(server.state.categories).toHaveLength(2)
  })

  it('repeats the server’s reason when a wiki page is still filed there', async () => {
    const server = createFakeServer({
      categories: twoCategories(),
      guides: [],
      pages: [pageFixture({ categoryId: 'c-em' })],
    })
    const user = userEvent.setup()
    renderCategories(server)

    await user.click(await screen.findByRole('button', { name: 'Delete Electron Microscopy' }))
    await user.click(screen.getByRole('button', { name: 'Delete category' }))

    expect(
      await screen.findByText("Move or delete this category's wiki pages first."),
    ).toBeInTheDocument()
  })
})

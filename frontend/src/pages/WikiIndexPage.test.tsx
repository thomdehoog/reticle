import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router-dom'

import { AppShell } from '../components/AppShell'
import { categoryFixture, createFakeServer, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { WikiIndexPage } from './WikiIndexPage'

function renderIndex(server: ReturnType<typeof createFakeServer>) {
  return renderWithApp(
    <Routes>
      <Route path="/w" element={<WikiIndexPage />} />
    </Routes>,
    { route: '/w', fetchImpl: server.fetchImpl },
  )
}

describe('WikiIndexPage', () => {
  it('lists the wiki pages with the category each belongs to', async () => {
    const server = createFakeServer({
      categories: [categoryFixture()],
      pages: [
        pageFixture({
          id: 'w-1',
          slug: 'immersion-oil',
          title: 'Immersion oil',
          summary: 'Which oil, and when.',
          categoryId: 'c-light',
          status: 'published',
        }),
        pageFixture({ id: 'w-2', slug: 'access', title: 'Getting access', status: 'published' }),
      ],
    })
    renderIndex(server)

    expect(await screen.findByRole('link', { name: /Immersion oil/ })).toHaveAttribute(
      'href',
      '/w/immersion-oil',
    )
    expect(screen.getByText('Light Microscopy')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Getting access/ })).toBeInTheDocument()
  })

  it('marks a landing page as belonging to its category', async () => {
    const server = createFakeServer({
      pages: [
        pageFixture({
          id: 'w-1',
          title: 'Light Microscopy',
          categoryId: 'c-light',
          isLanding: true,
          status: 'published',
        }),
      ],
    })
    renderIndex(server)

    expect(await screen.findByText('Section front page')).toBeInTheDocument()
  })

  it('says where to start when there is nothing yet', async () => {
    const server = createFakeServer({ pages: [] })
    renderIndex(server)

    expect(await screen.findByText(/No wiki pages yet/)).toBeInTheDocument()
  })
})

describe('the New page dialog', () => {
  function renderShell(server: ReturnType<typeof createFakeServer>) {
    return renderWithApp(
      <AppShell>
        <Routes>
          <Route path="/" element={<div>Home</div>} />
          <Route path="/w/:id/edit" element={<div>Page editor</div>} />
        </Routes>
      </AppShell>,
      { route: '/', fetchImpl: server.fetchImpl },
    )
  }

  it('creates a standalone article and opens it in the editor', async () => {
    const server = createFakeServer({ pages: [] })
    const user = userEvent.setup()
    renderShell(server)

    await user.click(await screen.findByRole('button', { name: /New page/ }))
    await user.type(screen.getByLabelText('Title'), 'Immersion oil')
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    expect(await screen.findByText('Page editor')).toBeInTheDocument()
    expect(server.state.pages[0].title).toBe('Immersion oil')
    expect(server.state.pages[0].categoryId).toBeNull()
    expect(server.state.pages[0].isLanding).toBe(false)
  })

  it('can start a category landing page directly', async () => {
    const server = createFakeServer({ pages: [] })
    const user = userEvent.setup()
    renderShell(server)

    await user.click(await screen.findByRole('button', { name: /New page/ }))
    await user.type(screen.getByLabelText('Title'), 'Light Microscopy')
    await user.selectOptions(screen.getByLabelText('Category'), 'c-light')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    expect(await screen.findByText('Page editor')).toBeInTheDocument()
    expect(server.state.pages[0].isLanding).toBe(true)
    expect(server.state.pages[0].categoryId).toBe('c-light')
  })

  /* The landing-page choice is meaningless without a category, and the server
     refuses it — so the control is unavailable rather than left to fail. */
  it('cannot mark a standalone article as a landing page', async () => {
    const server = createFakeServer({ pages: [] })
    const user = userEvent.setup()
    renderShell(server)

    await user.click(await screen.findByRole('button', { name: /New page/ }))
    expect(screen.getByRole('checkbox')).toBeDisabled()
  })

  it('surfaces the server refusing a second landing page for one category', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ id: 'w-1', categoryId: 'c-light', isLanding: true })],
    })
    const user = userEvent.setup()
    renderShell(server)

    await user.click(await screen.findByRole('button', { name: /New page/ }))
    await user.type(screen.getByLabelText('Title'), 'Another one')
    await user.selectOptions(screen.getByLabelText('Category'), 'c-light')
    await user.click(screen.getByRole('checkbox'))
    await user.click(screen.getByRole('button', { name: 'Create and start writing' }))

    expect(
      await screen.findByText('That category already has a landing page.'),
    ).toBeInTheDocument()
  })
})

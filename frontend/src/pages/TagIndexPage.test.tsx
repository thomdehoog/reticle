import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Route, Routes } from 'react-router'

import { createFakeServer, guideFixture, pageFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import { TagIndexPage } from './TagIndexPage'
import { TagPage } from './TagPage'

function renderTags(server: ReturnType<typeof createFakeServer>, route = '/t') {
  return renderWithApp(
    <Routes>
      <Route path="/t" element={<TagIndexPage />} />
      <Route path="/t/:tag" element={<TagPage />} />
    </Routes>,
    { route, fetchImpl: server.fetchImpl },
  )
}

describe('TagIndexPage', () => {
  it('lists every tag in use with how many guides carry it', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({ id: 'g1', status: 'published', tags: ['stellaris', 'confocal'] }),
        guideFixture({ id: 'g2', slug: 'g2', status: 'published', tags: ['confocal'] }),
      ],
    })
    renderTags(server)

    const confocal = await screen.findByRole('link', { name: /confocal/ })
    expect(confocal).toHaveAttribute('href', '/t/confocal')
    expect(confocal).toHaveTextContent('2')
    expect(screen.getByRole('link', { name: /stellaris/ })).toHaveTextContent('1')
  })

  it('says so plainly when nothing is tagged yet', async () => {
    const server = createFakeServer({ guides: [] })
    renderTags(server)

    expect(await screen.findByText('No tags are in use yet.')).toBeInTheDocument()
  })
})

describe('TagPage', () => {
  it('describes an empty result by what was actually asked for', async () => {
    const server = createFakeServer({ guides: [] })
    renderTags(server, '/t/stellaris')

    /* Not "no published guides": an author's own drafts are in this listing, so
       claiming the query was published-only contradicts what they can see. */
    expect(await screen.findByText(/Nothing carries the tag “stellaris”/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'See which tags are in use.' })).toHaveAttribute(
      'href',
      '/t',
    )
  })

  it('gathers the guides carrying the tag, whatever category they sit in', async () => {
    const server = createFakeServer({
      guides: [
        guideFixture({ id: 'g1', title: 'Stellaris startup', status: 'published', tags: ['stellaris'] }),
        guideFixture({
          id: 'g2',
          slug: 'g2',
          title: 'Widefield startup',
          status: 'published',
          tags: ['widefield'],
        }),
      ],
    })
    renderTags(server, '/t/stellaris')

    expect(await screen.findByRole('link', { name: /Stellaris startup/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Widefield startup/ })).not.toBeInTheDocument()
  })

  it('gathers the wikis carrying it as well as the guides', async () => {
    /* A tag names a group and a group holds either kind. Listing guides alone
       here would also make the number the tag index shows a lie, because that
       one counts both. */
    const server = createFakeServer({
      guides: [
        guideFixture({ id: 'g1', title: 'Stellaris startup', status: 'published', tags: ['stellaris'] }),
      ],
      pages: [
        pageFixture({ id: 'w1', title: 'Immersion oil', status: 'published', tags: ['stellaris'] }),
        pageFixture({ id: 'w2', slug: 'w2', title: 'Sample mounting', status: 'published' }),
      ],
    })
    renderTags(server, '/t/stellaris')

    expect(await screen.findByRole('link', { name: /Immersion oil/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Stellaris startup/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Sample mounting/ })).not.toBeInTheDocument()
    expect(screen.getByText('2 documents carry this tag.')).toBeInTheDocument()
  })
})

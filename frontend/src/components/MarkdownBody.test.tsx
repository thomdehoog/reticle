/**
 * The wiki renderer's two modes.
 *
 * A category page is shown at two levels of the tree, and the level with
 * sub-sections under it wants the page's prose without its guide lists. These
 * pin what "without" means: the list goes, the heading that introduced it goes
 * with it, and nothing that merely talks about a guide list is touched.
 */

import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { MarkdownBody } from './MarkdownBody'
import { renderWithApp } from '../test/harness'

/** A transport that answers every read with an empty list, so embeds settle. */
function emptyApi() {
  return vi.fn(
    async () => new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }),
  ) as unknown as typeof fetch
}

function renderWithoutGuideLists(body: string) {
  return renderWithApp(<MarkdownBody body={body} hideGuideLists />, { fetchImpl: emptyApi() })
}

const ZMB_LANDING_PAGE = `The light microscopy suite runs widefield, confocal and live-cell systems.

## Before your first session

You need an introduction on the system before you can book it.

## Starting up

\`\`\`guidelist
tags: confocal, startup
heading: Confocal start-up
\`\`\`
`

describe('MarkdownBody without guide lists', () => {
  it('keeps the prose the page opens with', async () => {
    renderWithoutGuideLists(ZMB_LANDING_PAGE)

    expect(
      await screen.findByText(/You need an introduction on the system before you can book it/),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Before your first session' })).toBeInTheDocument()
  })

  /**
   * The heading goes with its list, and that is the point of the pair. A
   * heading left standing over the space where a list used to be reads as a
   * page that failed to load, which is worse than either showing the list or
   * showing neither.
   */
  it('drops the list and the heading that introduced it', () => {
    renderWithoutGuideLists(ZMB_LANDING_PAGE)

    expect(screen.queryByRole('heading', { name: 'Starting up' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Confocal start-up' })).not.toBeInTheDocument()
    expect(screen.queryByText(/No guides are tagged/)).not.toBeInTheDocument()
  })

  it('asks the server for nothing, since nothing is being listed', () => {
    const fetchImpl = emptyApi()
    renderWithApp(<MarkdownBody body={ZMB_LANDING_PAGE} hideGuideLists />, { fetchImpl })

    const guideListings = vi
      .mocked(fetchImpl)
      .mock.calls.filter(([input]) => String(input).includes('/guides'))
    expect(guideListings).toHaveLength(0)
  })

  /* A heading that still has something under it is somebody's writing, not the
     list's label. */
  it('keeps a heading whose section is more than the list', () => {
    renderWithoutGuideLists(
      '## Confocal\n\nBook an introduction first.\n\n```guidelist\ntags: confocal\n```\n',
    )

    expect(screen.getByRole('heading', { name: 'Confocal' })).toBeInTheDocument()
    expect(screen.getByText('Book an introduction first.')).toBeInTheDocument()
  })

  /* The suppression reads the parsed document, so a code sample that merely
     mentions the fence survives — which a search-and-replace over the markdown
     would eventually eat. */
  it('leaves a code sample that talks about guide lists alone', () => {
    const { container } = renderWithoutGuideLists(
      '## Writing a guide list\n\nPut this in the page:\n\n```\n```guidelist\ntags: confocal\n```\n```\n',
    )

    expect(screen.getByRole('heading', { name: 'Writing a guide list' })).toBeInTheDocument()
    expect(container.querySelector('pre')?.textContent).toContain('tags: confocal')
  })

  it('renders the lists when it is not asked to hide them', async () => {
    renderWithApp(<MarkdownBody body={ZMB_LANDING_PAGE} />, { fetchImpl: emptyApi() })

    expect(await screen.findByRole('heading', { name: 'Starting up' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Confocal start-up' })).toBeInTheDocument()
  })
})

describe('embedding one named guide', () => {
  /** Answers the guide fetch with a real guide, and everything else emptily. */
  function apiWithGuide() {
    return vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/guides/oil-immersion')) {
        return new Response(
          JSON.stringify({
            id: 'g1',
            slug: 'oil-immersion',
            title: 'Immersion oil: which and when',
            summary: '',
            categoryId: 'c1',
            tags: [],
            isQuickLink: false,
            visibility: 'everyone',
            difficulty: 'easy',
            timeRequiredMinMinutes: null,
            timeRequiredMaxMinutes: null,
            introduction: '',
            conclusion: '',
            status: 'published',
            steps: [],
            author: { id: 'u1', displayName: 'A' },
            lastEditedBy: { id: 'u1', displayName: 'A' },
            contributors: [],
            viewCount: 0,
            createdAt: '2026-01-01T00:00:00Z',
            updatedAt: '2026-01-01T00:00:00Z',
            publishedAt: '2026-01-01T00:00:00Z',
            version: 1,
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        )
      }
      return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
    }) as unknown as typeof fetch
  }

  it('renders the named guide as an ordinary row', async () => {
    renderWithApp(<MarkdownBody body={'Windows:\n\n```guide\noil-immersion\n```'} />, {
      fetchImpl: apiWithGuide(),
    })

    expect(await screen.findByText('Immersion oil: which and when')).toBeInTheDocument()
    expect(screen.getByText('Windows:')).toBeInTheDocument()
  })

  it('keeps a single embed when the guide lists are suppressed', async () => {
    /* Suppression exists because a parent category repeated the whole list of
       guides living one level below it. One deliberately named link inside a
       sentence is not that, and removing it would break the prose around it. */
    renderWithApp(<MarkdownBody body={'Windows:\n\n```guide\noil-immersion\n```'} hideGuideLists />, {
      fetchImpl: apiWithGuide(),
    })

    expect(await screen.findByText('Immersion oil: which and when')).toBeInTheDocument()
  })

  it('says nothing to a reader when the address matches no guide', async () => {
    renderWithApp(<MarkdownBody body={'```guide\nnot-a-guide\n```'} />, { fetchImpl: emptyApi() })

    /* Silent for a reader: a dead entry is noise, and confirming that a guide
       exists but is not theirs to see is worse than saying nothing. */
    expect(await screen.findByText(/./)).toBeTruthy()
    expect(screen.queryByText(/No guide has the address/)).not.toBeInTheDocument()
  })
})

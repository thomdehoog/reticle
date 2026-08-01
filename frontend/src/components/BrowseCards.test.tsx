/**
 * The visual index is navigation, so its failures are navigation failures.
 *
 * Three of them are worth guarding. A card that shows no picture at all breaks
 * the premise of the screen — a wall of grey rectangles is a list of titles
 * with extra steps. A card whose drawn figure changes between visits stops
 * being recognisable, which is the only thing the figure is for. And a draft
 * that looks published on a wall of pictures is how somebody follows a
 * procedure nobody has finished writing.
 */

import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { CategoryTile, GuideCard, WikiCard } from './BrowseCards'
import { monogram } from './Thumbnail'
import { categoryFixture, guideFixture, pageSummaryFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import type { GuideSummary } from '../domain/types'

/**
 * These are presentational: they take what they render as a prop and never ask
 * the server for anything. The transport exists only to satisfy the harness,
 * and answering every call with a failure is the honest stub — if one of them
 * ever starts fetching, a test should notice.
 */
const noServer = (() =>
  Promise.reject(new Error('a browse card must not fetch'))) as unknown as typeof fetch

function render(ui: React.ReactNode) {
  return renderWithApp(ui, { fetchImpl: noServer })
}

function summary(overrides: Partial<GuideSummary> = {}): GuideSummary {
  const guide = guideFixture()
  return {
    id: guide.id,
    slug: guide.slug,
    title: guide.title,
    summary: guide.summary,
    categoryId: guide.categoryId,
    tags: guide.tags,
    difficulty: guide.difficulty,
    timeRequiredMinMinutes: guide.timeRequiredMinMinutes,
    timeRequiredMaxMinutes: guide.timeRequiredMaxMinutes,
    status: guide.status,
    stepCount: guide.steps.length,
    author: guide.author,
    viewCount: guide.viewCount,
    thumbnailUrl: null,
    updatedAt: guide.updatedAt,
    publishedAt: guide.publishedAt,
    ...overrides,
  }
}

describe('monogram', () => {
  it.each([
    ['Light Microscopy', 'LM'],
    ['CryoEM', 'C'],
    ['  spatial   biology  ', 'SB'],
    ['Präparation', 'P'],
  ])('takes the initials of %s', (name, expected) => {
    expect(monogram(name)).toBe(expected)
  })

  it('never comes back empty, whatever it was given', () => {
    for (const value of ['', '   ', '!!!', '···']) {
      expect(monogram(value).length).toBeGreaterThan(0)
    }
  })
})

describe('CategoryTile', () => {
  it('shows the section photograph when there is one', () => {
    const { container } = render(
      <CategoryTile
        category={categoryFixture({ imageUrl: '/api/media/m-1' })}
        guideCount={3}
      />,
    )

    expect(container.querySelector('img')).toHaveAttribute('src', '/api/media/m-1')
  })

  it('draws a figure when there is no photograph, rather than nothing', () => {
    const { container } = render(
      <CategoryTile category={categoryFixture()} guideCount={0} />,
    )

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg.thumb__figure')).not.toBeNull()
  })

  it('draws the same figure for the same name every time', () => {
    const first = render(<CategoryTile category={categoryFixture()} guideCount={0} />)
    const firstFigure = first.container.querySelector('svg.thumb__figure')?.innerHTML
    first.unmount()

    const second = render(<CategoryTile category={categoryFixture()} guideCount={0} />)

    expect(second.container.querySelector('svg.thumb__figure')?.innerHTML).toBe(firstFigure)
  })

  it('draws different figures for different names', () => {
    const light = render(<CategoryTile category={categoryFixture()} guideCount={0} />)
    const lightFigure = light.container.querySelector('svg.thumb__figure')?.innerHTML
    light.unmount()

    const cryo = render(
      <CategoryTile category={categoryFixture({ name: 'CryoEM' })} guideCount={0} />,
    )

    expect(cryo.container.querySelector('svg.thumb__figure')?.innerHTML).not.toBe(lightFigure)
  })

  it('leads to the section and counts what is in it', () => {
    render(<CategoryTile category={categoryFixture()} guideCount={3} />)

    expect(screen.getByRole('link')).toHaveAttribute('href', '/c/light-microscopy')
    expect(screen.getByText('3 guides')).toBeInTheDocument()
  })

  it('counts one guide in the singular', () => {
    render(<CategoryTile category={categoryFixture()} guideCount={1} />)
    expect(screen.getByText('1 guide')).toBeInTheDocument()
  })

  it('marks a holding section, which is reached by tag rather than by browsing', () => {
    render(<CategoryTile category={categoryFixture({ isHidden: true })} guideCount={86} />)
    expect(screen.getByText('Hidden')).toBeInTheDocument()
  })
})

describe('GuideCard', () => {
  it("shows the guide's own first step image", () => {
    const { container } = render(
      <GuideCard guide={summary({ thumbnailUrl: '/api/media/m-9' })} />,
    )

    expect(container.querySelector('img')).toHaveAttribute('src', '/api/media/m-9')
  })

  it('carries what a reader chooses on: steps, difficulty and how long it takes', () => {
    render(
      <GuideCard
        guide={summary({ stepCount: 5, timeRequiredMinMinutes: 30, timeRequiredMaxMinutes: 90 })}
      />,
    )

    expect(screen.getByText(/5 steps/)).toBeInTheDocument()
    expect(screen.getByText('Moderate')).toBeInTheDocument()
    expect(screen.getByText('30 min – 1 h 30 min')).toBeInTheDocument()
  })

  it('says nothing about time when nobody estimated it', () => {
    render(
      <GuideCard guide={summary({ timeRequiredMinMinutes: null, timeRequiredMaxMinutes: null })} />,
    )

    expect(screen.queryByText(/min/)).toBeNull()
  })

  it('marks a draft, so nobody follows an unfinished procedure', () => {
    render(<GuideCard guide={summary({ status: 'draft' })} />)
    expect(screen.getByText('Draft')).toBeInTheDocument()
  })

  it('says nothing about status on a published guide', () => {
    render(<GuideCard guide={summary({ status: 'published' })} />)
    expect(screen.queryByText('Draft')).toBeNull()
  })

  it('can be pointed somewhere other than the reader, for an author’s own drafts', () => {
    render(<GuideCard guide={summary()} to="/g/g-confocal/edit" />)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/g/g-confocal/edit')
  })
})

describe('WikiCard', () => {
  it('distinguishes a section front page from an ordinary article', () => {
    const landing = render(<WikiCard page={pageSummaryFixture({ isLanding: true })} />)
    expect(screen.getByText('Section front page')).toBeInTheDocument()
    landing.unmount()

    render(<WikiCard page={pageSummaryFixture({ isLanding: false })} />)
    expect(screen.getByText('Wiki page')).toBeInTheDocument()
  })

  it('names the section it belongs to when it is seen away from it', () => {
    render(<WikiCard page={pageSummaryFixture()} context="Light Microscopy" />)
    expect(screen.getByText('Light Microscopy')).toBeInTheDocument()
  })

  it('uses the hero image when the page has one', () => {
    const { container } = render(
      <WikiCard page={pageSummaryFixture({ heroImageUrl: '/api/media/m-3' })} />,
    )
    expect(container.querySelector('img')).toHaveAttribute('src', '/api/media/m-3')
  })
})

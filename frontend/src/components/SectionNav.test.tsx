/**
 * The list beside a guide is scoped, and that scoping is the whole point.
 *
 * It shows the section the reader is in — not the institute. A sidebar that
 * listed everything would be a second, worse copy of the front page, and on a
 * corpus where one hidden section holds eighty-six confocal guides it would be
 * unusable at exactly the moment it matters. The other failure it guards
 * against is quieter: a list that does not say which item is open leaves
 * somebody working through twenty procedures for one instrument unable to tell
 * where they are.
 */

import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { SectionNav } from './SectionNav'
import { guideFixture, pageSummaryFixture } from '../test/fakeServer'
import { renderWithApp } from '../test/harness'
import type { GuideSummary } from '../domain/types'

const noServer = (() =>
  Promise.reject(new Error('the section list must not fetch'))) as unknown as typeof fetch

function render(ui: React.ReactNode) {
  return renderWithApp(ui, { fetchImpl: noServer })
}

function guide(id: string, title: string): GuideSummary {
  const base = guideFixture()
  return {
    id,
    slug: title.toLowerCase().replace(/\s+/g, '-'),
    title,
    summary: '',
    categoryId: base.categoryId,
    tags: [],
    difficulty: 'moderate',
    timeRequiredMinMinutes: null,
    timeRequiredMaxMinutes: null,
    status: 'published',
    stepCount: 3,
    author: base.author,
    viewCount: 0,
    thumbnailUrl: null,
    updatedAt: base.updatedAt,
    publishedAt: base.publishedAt,
  }
}

const SECTION = { name: 'Light Microscopy', slug: 'light-microscopy' }

describe('SectionNav', () => {
  it('lists the section it was given, and leads back to it', () => {
    render(
      <SectionNav
        section={SECTION}
        pages={[]}
        guides={[guide('g-1', 'Starting up'), guide('g-2', 'Shutting down')]}
        currentId="g-1"
      />,
    )

    expect(screen.getByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
    expect(screen.getByRole('link', { name: /Starting up/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Shutting down/ })).toBeInTheDocument()
  })

  it('marks the one being read, so a reader can tell where they are', () => {
    render(
      <SectionNav
        section={SECTION}
        pages={[]}
        guides={[guide('g-1', 'Starting up'), guide('g-2', 'Shutting down')]}
        currentId="g-2"
      />,
    )

    expect(screen.getByRole('link', { name: /Shutting down/ })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('link', { name: /Starting up/ })).not.toHaveAttribute('aria-current')
  })

  it('carries the wiki pages as well as the guides, grouped', () => {
    render(
      <SectionNav
        section={SECTION}
        pages={[pageSummaryFixture({ id: 'w-1', slug: 'immersion-oil', title: 'Immersion oil' })]}
        guides={[guide('g-1', 'Starting up')]}
        currentId="g-1"
      />,
    )

    const navigation = screen.getByRole('navigation')
    expect(within(navigation).getByText('Pages')).toBeInTheDocument()
    expect(within(navigation).getByText('Guides')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Immersion oil/ })).toHaveAttribute(
      'href',
      '/w/immersion-oil',
    )
  })

  it("leaves out the section's own front page, which is the section", () => {
    render(
      <SectionNav
        section={SECTION}
        pages={[
          pageSummaryFixture({ id: 'w-1', title: 'Light Microscopy', isLanding: true }),
          pageSummaryFixture({ id: 'w-2', slug: 'immersion-oil', title: 'Immersion oil' }),
        ]}
        guides={[guide('g-1', 'Starting up')]}
        currentId="g-1"
      />,
    )

    expect(screen.queryByRole('link', { name: /Immersion oil/ })).toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: /^Light Microscopy$/ }),
    ).toHaveAttribute('href', '/c/light-microscopy')
  })

  it('says nothing at all when there is nothing to move between', () => {
    const { container } = render(
      <SectionNav section={SECTION} pages={[]} guides={[guide('g-1', 'Starting up')]} currentId="g-1" />,
    )

    expect(container.querySelector('.section-nav')).toBeNull()
  })

  it('still works for a page that belongs to no section', () => {
    render(
      <SectionNav
        section={null}
        pages={[
          pageSummaryFixture({ id: 'w-1', slug: 'access', title: 'Getting access' }),
          pageSummaryFixture({ id: 'w-2', slug: 'storage', title: 'Data storage' }),
        ]}
        guides={[]}
        currentId="w-1"
      />,
    )

    expect(screen.getByRole('link', { name: /Data storage/ })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Light Microscopy' })).toBeNull()
  })
})

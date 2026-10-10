import { useSuspenseQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { useApi } from '../api/context'
import { EmptyState } from '../components/ui'
import { tagQueries } from '../queries/tags'

type Order = 'name' | 'count'

/**
 * Every tag, with how many guides carry it.
 *
 * Tags are how ZMB's guides are actually found — far more than the category
 * tree — so they get an index of their own rather than being reachable only
 * from a guide that happens to carry one. With well over a hundred of them, the
 * filter box is the main control, and sorting by count answers the other
 * question people bring here: what is there most of?
 */
export function TagsPage() {
  const api = useApi()
  const { data: tags } = useSuspenseQuery(tagQueries.list(api))
  const [filter, setFilter] = useState('')
  const [order, setOrder] = useState<Order>('name')

  const wanted = filter.trim().toLowerCase()
  const shown = tags
    .filter(
      (tag) =>
        wanted === '' || tag.name.toLowerCase().includes(wanted) || tag.slug.includes(wanted),
    )
    .sort((a, b) =>
      order === 'count'
        ? b.guideCount - a.guideCount || a.name.localeCompare(b.name)
        : a.name.localeCompare(b.name),
    )

  return (
    <>
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep" aria-hidden="true">
          /
        </span>
        <span>Tags</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>Tags</h1>
          <p className="page-header__sub">
            A tag gathers every guide about one instrument, technique or program, whichever
            category it is filed in.
          </p>
        </div>
      </div>

      {tags.length === 0 ? (
        <EmptyState>
          No tags yet. A tag appears here as soon as a published guide carries it.
        </EmptyState>
      ) : (
        <>
          <div className="list-controls">
            <label className="visually-hidden" htmlFor="tag-filter">
              Filter tags
            </label>
            <input
              id="tag-filter"
              className="input list-controls__filter"
              type="search"
              placeholder="Filter tags…"
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            />
            <div className="segmented" role="group" aria-label="Sort tags">
              <button
                type="button"
                className="button button--sm"
                aria-pressed={order === 'name'}
                onClick={() => setOrder('name')}
              >
                A–Z
              </button>
              <button
                type="button"
                className="button button--sm"
                aria-pressed={order === 'count'}
                onClick={() => setOrder('count')}
              >
                Most guides
              </button>
            </div>
            <span className="list-controls__count" role="status">
              {shown.length === tags.length
                ? `${tags.length} ${tags.length === 1 ? 'tag' : 'tags'}`
                : `${shown.length} of ${tags.length} tags`}
            </span>
          </div>

          {shown.length === 0 ? (
            <EmptyState>No tag matches “{filter.trim()}”.</EmptyState>
          ) : (
            <ul className="tag-index">
              {shown.map((tag) => (
                <li key={tag.id}>
                  <Link className="tag-index__item" to="/t/$tag" params={{ tag: tag.slug }}>
                    <span className="tag-index__name">{tag.name}</span>
                    <span className="tag-index__count">
                      {tag.guideCount}
                      <span className="visually-hidden">
                        {tag.guideCount === 1 ? ' guide' : ' guides'}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </>
  )
}

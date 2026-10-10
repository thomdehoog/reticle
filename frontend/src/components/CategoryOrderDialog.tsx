import { useState } from 'react'

import { buildCategoryTree, moveAmongSiblings, type CategoryNode } from '../domain/category'
import type { Category } from '../domain/types'
import { useReorderCategories } from '../queries/categories'
import { IconChevronDown, IconChevronUp } from './icons'
import { ErrorAlert, Modal } from './ui'

interface Row {
  category: Category
  depth: number
  isFirst: boolean
  isLast: boolean
}

function flatten(nodes: CategoryNode[], depth = 0): Row[] {
  return nodes.flatMap((node, index) => [
    { category: node, depth, isFirst: index === 0, isLast: index === nodes.length - 1 },
    ...flatten(node.children, depth + 1),
  ])
}

/**
 * Puts categories in the order the front page shows them.
 *
 * Buttons rather than dragging: the list is short, it is rearranged a few times
 * a year, and up/down works the same with a mouse, a keyboard and a finger. A
 * category moves among its siblings only — moving it under another parent is
 * what "Inside" in the category's own dialog is for.
 *
 * Hidden categories are listed as well. They do not appear on the front page,
 * but they do appear, in this order, in every category picker.
 */
export function CategoryOrderDialog({
  categories,
  onClose,
}: {
  categories: Category[]
  onClose: () => void
}) {
  const reorder = useReorderCategories()
  const [announcement, setAnnouncement] = useState('')

  const rows = flatten(buildCategoryTree(categories))

  function move(category: Category, delta: -1 | 1) {
    /* Ignored rather than disabled while a move is being saved: a disabled
       button drops keyboard focus, and the usual use is several presses in a
       row on the same one. */
    if (reorder.isPending) return
    const changes = moveAmongSiblings(categories, category.id, delta)
    if (changes.length === 0) return
    reorder.mutate(changes, {
      onSuccess: () => setAnnouncement(`Moved ${category.name} ${delta < 0 ? 'up' : 'down'}.`),
    })
  }

  return (
    <Modal title="Arrange categories" onClose={onClose}>
      <p className="field__hint dialog-lead">
        This is the order categories appear in on the front page and in every category picker.
      </p>

      <ErrorAlert error={reorder.error} />

      <ul className="order-list">
        {rows.map(({ category, depth, isFirst, isLast }) => (
          <li
            key={category.id}
            className="order-list__row"
            style={{ paddingLeft: `${0.6 + depth * 1.25}rem` }}
          >
            <span className="order-list__name">
              {category.name}
              {category.isHidden && <span className="order-list__note"> (hidden)</span>}
            </span>
            <button
              type="button"
              className="button button--ghost button--icon"
              aria-label={`Move ${category.name} up`}
              disabled={isFirst}
              onClick={() => move(category, -1)}
            >
              <IconChevronUp />
            </button>
            <button
              type="button"
              className="button button--ghost button--icon"
              aria-label={`Move ${category.name} down`}
              disabled={isLast}
              onClick={() => move(category, 1)}
            >
              <IconChevronDown />
            </button>
          </li>
        ))}
      </ul>

      <p className="visually-hidden" role="status">
        {announcement}
      </p>

      <div className="page-actions">
        <button className="button button--primary" type="button" onClick={onClose}>
          Done
        </button>
      </div>
    </Modal>
  )
}

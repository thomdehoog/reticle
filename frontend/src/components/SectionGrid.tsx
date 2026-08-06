/**
 * The wall of sections, and what an administrator can do to it without leaving
 * the page they are looking at.
 *
 * One component for both places sections are shown — the front page and the
 * sections inside a section — because the two were the same grid already, and a
 * second copy is how the front page and the level below it start behaving
 * differently.
 *
 * A reader gets exactly what they got before: tiles, and nothing else. Every
 * affordance here is behind `admin`, which is the same rank the server demands
 * for all three of these operations, so a viewer who forges the markup still
 * gets a 403.
 *
 * **Deleting is confirmed but not warned about.** The server refuses to delete a
 * section that still holds guides, pages or sub-sections, and says which — so
 * the dangerous case is already impossible and the dialog does not need to
 * describe it. What the dialog is for is the *other* mistake: an empty section
 * deleted by a mis-aimed click on a tile the eye had already moved past.
 *
 * **Order is dragged, and also nudged.** Dragging is what an administrator
 * reaches for on a wall of pictures, and it is not reachable from a keyboard;
 * the arrows on the categories admin screen remain the way to do this without a
 * mouse. Neither is a fallback for the other — they are the same field written
 * two ways, and the screen that suits the hand at the time.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { useState } from 'react'

import { useApi, useAuth } from '../auth/AuthContext'
import type { Category } from '../domain/types'
import { CategoryTile, NewCategoryTile, TileGrid } from './BrowseCards'
import { ErrorAlert, Modal } from './ui'

export function SectionGrid({
  categories,
  parentId = null,
  onChanged,
}: {
  categories: Category[]
  /** Which section these sit in, so a new one is made in the right place. */
  parentId?: string | null
  /** Called after an order change or a deletion, to re-read the tree. */
  onChanged: () => void
}) {
  const api = useApi()
  const { can } = useAuth()
  const admin = can('admin')

  const [confirming, setConfirming] = useState<Category | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)

  async function remove(category: Category) {
    setBusy(true)
    setFailure(null)
    try {
      await api.deleteCategory(category.id)
      setConfirming(null)
      onChanged()
    } catch (cause) {
      setFailure(cause)
    } finally {
      setBusy(false)
    }
  }

  /**
   * Drop `dragged` where `target` is, and write the order back.
   *
   * Every tile from the smaller of the two positions onward is renumbered,
   * because `orderIndex` is a position and not a weight: writing one row's new
   * number and leaving the rest would put two sections on the same index and
   * let the tie decide the order.
   */
  async function reorder(draggedId: string, targetId: string) {
    if (draggedId === targetId) return
    const from = categories.findIndex((candidate) => candidate.id === draggedId)
    const to = categories.findIndex((candidate) => candidate.id === targetId)
    if (from < 0 || to < 0) return

    const next = [...categories]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)

    setFailure(null)
    try {
      for (const [index, category] of next.entries()) {
        if (category.orderIndex !== index) {
          await api.updateCategory(category.id, { orderIndex: index })
        }
      }
      onChanged()
    } catch (cause) {
      setFailure(cause)
    }
  }

  return (
    <>
      <ErrorAlert error={failure} />

      <TileGrid>
        {categories.map((category) => (
          <div
            key={category.id}
            className={
              over === category.id && dragging !== category.id ? 'tile-drop tile-drop--over' : 'tile-drop'
            }
            draggable={admin}
            onDragStart={(event) => {
              setDragging(category.id)
              event.dataTransfer.effectAllowed = 'move'
              /* Firefox will not start a drag without data on it. */
              event.dataTransfer.setData('text/plain', category.id)
            }}
            onDragEnd={() => {
              setDragging(null)
              setOver(null)
            }}
            onDragOver={(event) => {
              if (!admin || !dragging) return
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
              setOver(category.id)
            }}
            onDragLeave={() => setOver((current) => (current === category.id ? null : current))}
            onDrop={(event) => {
              event.preventDefault()
              const draggedId = dragging ?? event.dataTransfer.getData('text/plain')
              setDragging(null)
              setOver(null)
              if (draggedId) void reorder(draggedId, category.id)
            }}
          >
            <CategoryTile
              category={category}
              draggable={admin}
              onDelete={admin ? setConfirming : undefined}
            />
          </div>
        ))}

        {admin && <NewCategoryTile parentId={parentId} />}
      </TileGrid>

      {confirming && (
        <Modal title={`Delete ${confirming.name}?`} onClose={() => setConfirming(null)}>
          <ErrorAlert error={failure} />
          <p>
            The section and its picture go. Anything inside it has to be moved first — the server
            refuses while it still holds guides, wiki pages or sections of its own, and says which.
          </p>
          <div className="page-actions">
            <button
              className="button button--danger"
              type="button"
              disabled={busy}
              onClick={() => void remove(confirming)}
            >
              {busy ? 'Deleting…' : 'Delete section'}
            </button>
            <button className="button" type="button" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

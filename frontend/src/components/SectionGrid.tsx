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
 * **Deleting takes everything underneath, and asks for a password.** The server
 * used to refuse while a section still held anything, which left emptying one a
 * manual chore and made the button unable to do what it said. It does the whole
 * thing now — sub-sections, guides, wiki pages — and none of it is archived, so
 * the dialog says so plainly and the password is what stands between a tile and
 * a body of documentation. It is checked on the server as well; a confirmation
 * that lived only here would guard the mis-click and nothing else.
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
  canAdd = true,
  emptyIds,
  onChanged,
}: {
  categories: Category[]
  /** Which section these sit in, so a new one is made in the right place. */
  parentId?: string | null
  /**
   * Whether a section may be added here at all.
   *
   * False inside a sub-section: the tree is two deep and the server refuses a
   * third level, so offering the tile would be offering a 422.
   */
  canAdd?: boolean
  /**
   * Which of these a reader would not be shown, because nothing is published
   * under them. Only an administrator is given any, and only so that a section
   * just made does not vanish; the tile wears a mark saying so.
   */
  emptyIds?: Set<string>
  /** Called after an order change or a deletion, to re-read the tree. */
  onChanged: () => void
}) {
  const api = useApi()
  const { can } = useAuth()
  const admin = can('admin')

  const [confirming, setConfirming] = useState<Category | null>(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const [dragging, setDragging] = useState<string | null>(null)

  /**
   * The order on screen, which during a drag is ahead of the order on the
   * server.
   *
   * A tile moves as soon as the pointer is over the place it would land, so
   * what the grid shows while somebody is still holding the mouse down is the
   * result of letting go — the arrangement is the preview, and there is no
   * marker to interpret. Only when the drag ends is any of it written.
   */
  const [order, setOrder] = useState(categories)
  /* Adjusted during render rather than in an effect: an effect would paint the
     stale order first and then correct it, and React re-renders this component
     before the browser sees either. The remembered list is what says the
     property genuinely changed, as opposed to this component simply rendering
     again mid-drag. */
  const [rendered, setRendered] = useState(categories)
  if (rendered !== categories) {
    setRendered(categories)
    setOrder(categories)
  }

  async function remove(category: Category) {
    setBusy(true)
    setFailure(null)
    try {
      await api.deleteCategory(category.id, password)
      setConfirming(null)
      setPassword('')
      onChanged()
    } catch (cause) {
      setFailure(cause)
    } finally {
      setBusy(false)
    }
  }

  /** Move the dragged tile to where `targetId` currently sits, on screen only. */
  function previewMove(draggedId: string, targetId: string) {
    if (draggedId === targetId) return
    setOrder((current) => {
      const from = current.findIndex((candidate) => candidate.id === draggedId)
      const to = current.findIndex((candidate) => candidate.id === targetId)
      if (from < 0 || to < 0 || from === to) return current
      const next = [...current]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }

  /**
   * Write down what the grid is already showing.
   *
   * Every tile from the first moved position onward is renumbered, because
   * `orderIndex` is a position and not a weight: writing one row's new number
   * and leaving the rest would put two sections on the same index and let the
   * tie decide which came first.
   *
   * `onChanged` is not called on success. The screen is already right — it has
   * been since the pointer passed the tile — and re-reading the tree only to
   * redraw the same order is a flicker for nothing. It is called on failure,
   * where the screen is showing an arrangement the server refused and the truth
   * has to come back.
   */
  async function commitOrder() {
    const moved = order.filter((category, index) => category.orderIndex !== index)
    if (moved.length === 0) return

    setFailure(null)
    try {
      for (const category of moved) {
        await api.updateCategory(category.id, { orderIndex: order.indexOf(category) })
      }
    } catch (cause) {
      setFailure(cause)
      onChanged()
    }
  }

  return (
    <>
      <ErrorAlert error={failure} />

      <TileGrid>
        {order.map((category) => (
          <div
            key={category.id}
            className={`tile-drop${dragging === category.id ? ' tile-drop--lifted' : ''}`}
            draggable={admin}
            onDragStart={(event) => {
              setDragging(category.id)
              event.dataTransfer.effectAllowed = 'move'
              /* Firefox will not start a drag without data on it. */
              event.dataTransfer.setData('text/plain', category.id)
            }}
            onDragEnd={() => {
              setDragging(null)
              void commitOrder()
            }}
            /* `dragEnter` and not `dragOver`: entering fires once per tile
               crossed, where `dragOver` fires every few pixels and would move
               the same tile over and over while the pointer sat still. */
            onDragEnter={() => {
              if (admin && dragging) previewMove(dragging, category.id)
            }}
            onDragOver={(event) => {
              if (!admin || !dragging) return
              /* Both of these are needed for a drop to be allowed at all, which
                 is what makes `dragEnd` mean "let go here" rather than
                 "cancelled". */
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
            }}
            onDrop={(event) => event.preventDefault()}
          >
            <CategoryTile
              category={category}
              draggable={admin}
              onDelete={admin ? setConfirming : undefined}
              emptyToReaders={admin && emptyIds?.has(category.id)}
            />
          </div>
        ))}

        {admin && canAdd && <NewCategoryTile parentId={parentId} />}
      </TileGrid>

      {confirming && (
        <Modal
          title={`Delete ${confirming.name}?`}
          onClose={() => {
            setConfirming(null)
            setPassword('')
          }}
        >
          <ErrorAlert error={failure} />
          <p>
            <strong>Everything inside it goes as well</strong> — its sub-sections, and every guide
            and wiki page filed in any of them. They are deleted, not archived: this is the one
            place in Reticle where content does not come back.
          </p>
          {/* The password is why this can be allowed to do what it says. The
              server checks it too — a confirmation that lived only here would
              stop the mis-click and nothing else. */}
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void remove(confirming)
            }}
          >
            <div className="field">
              <label className="field__label" htmlFor="delete-password">
                Your password
              </label>
              <input
                id="delete-password"
                className="input"
                type="password"
                /* Every layer here exists because the one above it is ignored.
                   "off" is ignored by browsers on password fields; "new-password"
                   tells them this is not the saved credential, which Chrome and
                   Firefox honour. The three data attributes are 1Password,
                   LastPass and Bitwarden, which read their own and not the
                   standard one. And "readOnly" until the field is touched is what
                   catches the rest: a manager fills on load, and there is nothing
                   fillable on load. It clears on focus, so typing is unaffected.

                   No autoFocus, deliberately — focusing it on open would hand a
                   manager the moment it is waiting for. */
                autoComplete="new-password"
                data-1p-ignore
                data-lpignore="true"
                data-bwignore
                readOnly
                onFocus={(event) => {
                  event.currentTarget.readOnly = false
                }}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            <div className="page-actions">
              <button
                className="button button--danger"
                type="submit"
                disabled={busy || password === ''}
              >
                {busy ? 'Deleting…' : 'Delete section'}
              </button>
              <button
                className="button"
                type="button"
                onClick={() => {
                  setConfirming(null)
                  setPassword('')
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        </Modal>
      )}
    </>
  )
}

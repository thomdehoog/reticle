/**
 * Where an administrator arranges the categories.
 *
 * Categories are the shelves the guides sit on - Light Microscopy, Electron
 * Microscopy, and so on. They can be nested, reordered, given a cover picture, or
 * hidden from the front page while still being reachable by tag.
 *
 * Only administrators see this. A category is shared by everybody, so renaming
 * one changes what the whole institute sees.
 */

import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { IconChevronDown, IconChevronUp, IconPlus, IconTrash } from '../components/icons'
import { Thumbnail } from '../components/Thumbnail'
import { EmptyState, ErrorAlert, Modal, Spinner } from '../components/ui'
import type { Category } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { buildCategoryTree, type CategoryNode } from '../hooks/useCategories'

/** The rows of the tree, flattened, each carrying how deep it sits. */
function flatten(nodes: CategoryNode[], depth = 0): { category: CategoryNode; depth: number }[] {
  return nodes.flatMap((node) => [
    { category: node, depth },
    ...flatten(node.children, depth + 1),
  ])
}

/**
 * A category, edited in place.
 *
 * The form is a dialog rather than an inline row of inputs because re-parenting
 * a category moves everything under it, and that is not a decision to make by
 * brushing past a select box in a table.
 */
function CategoryDialog({
  category,
  categories,
  onClose,
  onSaved,
}: {
  category: Category | null
  categories: Category[]
  onClose: () => void
  onSaved: () => void
}) {
  const api = useApi()
  const [name, setName] = useState(category?.name ?? '')
  const [description, setDescription] = useState(category?.description ?? '')
  const [parentId, setParentId] = useState(category?.parentId ?? '')
  const [isHidden, setIsHidden] = useState(category?.isHidden ?? false)
  const [heroMediaId, setHeroMediaId] = useState(category?.heroMediaId ?? null)
  const [heroUrl, setHeroUrl] = useState(category?.imageUrl ?? null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  /**
   * The picture is what the section is browsed by, so setting it belongs here
   * rather than in a separate screen: an administrator creating "CryoEM" is
   * exactly the person who knows which photograph says CryoEM.
   */
  async function onPickImage(file: File | null) {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      const media = await api.uploadMedia(file)
      setHeroMediaId(media.id)
      setHeroUrl(media.url)
    } catch (cause) {
      setError(cause)
    } finally {
      setUploading(false)
    }
  }

  /**
   * A category cannot be moved inside itself or inside its own descendants —
   * that detaches the whole branch from the tree and the guides under it stop
   * being reachable by browsing.
   */
  const descendants = new Set<string>()
  if (category) {
    const collect = (id: string) => {
      descendants.add(id)
      for (const child of categories.filter((candidate) => candidate.parentId === id)) {
        collect(child.id)
      }
    }
    collect(category.id)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      if (category) {
        await api.updateCategory(category.id, {
          name: name.trim(),
          description: description.trim(),
          parentId: parentId === '' ? null : parentId,
          isHidden,
          heroMediaId,
        })
      } else {
        await api.createCategory({
          name: name.trim(),
          description: description.trim(),
          parentId: parentId === '' ? null : parentId,
          isHidden,
          heroMediaId,
        })
      }
      onSaved()
      onClose()
    } catch (cause) {
      setError(cause)
      setSubmitting(false)
    }
  }

  return (
    <Modal title={category ? `Edit ${category.name}` : 'New category'} onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={error} />

        <div className="field">
          <label className="field__label" htmlFor="category-name">
            Name
          </label>
          <input
            id="category-name"
            className="input"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="category-description">
            Description
          </label>
          <input
            id="category-description"
            className="input"
            value={description}
            placeholder="One line, shown on the category card."
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="category-parent">
            Sits under
          </label>
          <select
            id="category-parent"
            className="select"
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
          >
            <option value="">Nothing — a top-level category</option>
            {categories
              .filter((candidate) => !descendants.has(candidate.id))
              .map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))}
          </select>
        </div>

        <div className="field">
          <span className="field__label">Picture</span>
          <div className="hero-picker">
            <Thumbnail seed={name || 'New section'} src={heroUrl} className="hero-picker__preview" />
            <div className="hero-picker__controls">
              <input
                id="category-hero"
                type="file"
                accept="image/*"
                onChange={(event) => void onPickImage(event.target.files?.[0] ?? null)}
              />
              {heroUrl && (
                <button
                  className="button"
                  type="button"
                  onClick={() => {
                    setHeroMediaId(null)
                    setHeroUrl(null)
                  }}
                >
                  Remove
                </button>
              )}
              {uploading && <span className="save-state">Uploading…</span>}
            </div>
          </div>
          <span className="field__hint">
            Browsing is done by eye. Without a picture the section is shown with a drawn figure
            derived from its name, which is recognisable but says nothing about the instrument.
          </span>
        </div>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={isHidden}
            onChange={(event) => setIsHidden(event.target.checked)}
          />
          <span>Hide from the category tree</span>
        </label>
        <span className="field__hint">
          A hidden category still holds its guides and its URL still works — it just does not appear
          when people browse. This is what a holding category is for: guides that are found by tag
          from a wiki page rather than by opening a folder.
        </span>

        <div className="page-actions" style={{ marginTop: '1.25rem' }}>
          <button className="button button--primary" type="submit" disabled={submitting}>
            {submitting ? 'Saving…' : category ? 'Save changes' : 'Create category'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Category management.
 *
 * Both the account screen and the people screen told users that admins manage
 * "people and categories", and only half of that was true: categories could be
 * created by the seed script and by nothing else. Ordering is a pair of nudge
 * buttons rather than drag-and-drop, because this list is edited perhaps twice
 * a year and a keyboard-reachable button beats a gesture nobody remembers.
 */
export function CategoriesPage() {
  const api = useApi()
  const { data, error, loading, reload } = useAsync(() => api.listCategories(), [api])

  const [editing, setEditing] = useState<Category | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirming, setConfirming] = useState<Category | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  /* Kept apart from `actionError` so the refusal appears in the dialog the
     admin is looking at, and only there. */
  const [deleteError, setDeleteError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const categories = data ?? []
  const rows = flatten(buildCategoryTree(categories))

  /**
   * Reordering swaps this category's `orderIndex` with its neighbour's, so the
   * two writes are enough and no third category shifts underneath the admin.
   */
  async function move(category: Category, delta: number) {
    const siblings = categories
      .filter((candidate) => candidate.parentId === category.parentId)
      .sort((a, b) => a.orderIndex - b.orderIndex || a.name.localeCompare(b.name))
    const at = siblings.findIndex((candidate) => candidate.id === category.id)
    const swapWith = siblings[at + delta]
    if (!swapWith) return

    setBusy(true)
    setActionError(null)
    try {
      await api.updateCategory(category.id, { orderIndex: swapWith.orderIndex })
      await api.updateCategory(swapWith.id, { orderIndex: category.orderIndex })
      reload()
    } catch (cause) {
      setActionError(cause)
      /* Reload on failure too: the first write may have landed and the second
         not, and a list showing the order the admin asked for rather than the
         order the server holds is worse than the error itself. */
      reload()
    } finally {
      setBusy(false)
    }
  }

  async function toggleHidden(category: Category) {
    setBusy(true)
    setActionError(null)
    try {
      await api.updateCategory(category.id, { isHidden: !category.isHidden })
      reload()
    } catch (cause) {
      setActionError(cause)
    } finally {
      setBusy(false)
    }
  }

  async function remove(category: Category) {
    setBusy(true)
    setDeleteError(null)
    try {
      await api.deleteCategory(category.id)
      setConfirming(null)
      reload()
    } catch (cause) {
      /* The server counts what is still inside and says so; repeating its own
         sentence is more use than "could not delete". */
      setDeleteError(cause)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />

  return (
    <>
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        <span className="breadcrumb__sep">/</span>
        <span>Categories</span>
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>Categories</h1>
          <p className="page-header__sub">
            Where guides are filed. Everyone browses this tree, so keep it short.
          </p>
        </div>
        <div className="page-actions">
          <button className="button button--primary" type="button" onClick={() => setCreating(true)}>
            <IconPlus />
            New category
          </button>
        </div>
      </div>

      <ErrorAlert error={actionError} />

      {rows.length === 0 ? (
        <EmptyState>No categories yet.</EmptyState>
      ) : (
        <div className="card">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Visibility</th>
                <th>Order</th>
                <th>
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ category, depth }) => (
                <tr key={category.id}>
                  <td>
                    <span style={{ paddingLeft: `${depth * 1.25}rem` }}>
                      <Link to={`/c/${category.slug}`}>{category.name}</Link>
                    </span>
                    {category.description && (
                      <div className="category-admin__desc">{category.description}</div>
                    )}
                  </td>
                  <td>
                    <button
                      className="button button--sm"
                      type="button"
                      disabled={busy}
                      onClick={() => void toggleHidden(category)}
                    >
                      {category.isHidden ? 'Hidden — show it' : 'Visible — hide it'}
                    </button>
                  </td>
                  <td>
                    <div className="category-admin__order">
                      <button
                        className="button button--sm button--icon"
                        type="button"
                        aria-label={`Move ${category.name} up`}
                        disabled={busy}
                        onClick={() => void move(category, -1)}
                      >
                        <IconChevronUp size={14} />
                      </button>
                      <button
                        className="button button--sm button--icon"
                        type="button"
                        aria-label={`Move ${category.name} down`}
                        disabled={busy}
                        onClick={() => void move(category, 1)}
                      >
                        <IconChevronDown size={14} />
                      </button>
                    </div>
                  </td>
                  <td>
                    <div className="category-admin__order">
                      <button
                        className="button button--sm"
                        type="button"
                        onClick={() => setEditing(category)}
                      >
                        Edit
                      </button>
                      <button
                        className="button button--sm button--danger"
                        type="button"
                        aria-label={`Delete ${category.name}`}
                        onClick={() => {
                          setDeleteError(null)
                          setConfirming(category)
                        }}
                      >
                        <IconTrash size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {(creating || editing) && (
        <CategoryDialog
          category={editing}
          categories={categories}
          onClose={() => {
            setCreating(false)
            setEditing(null)
          }}
          onSaved={reload}
        />
      )}

      {confirming && (
        <Modal title={`Delete ${confirming.name}?`} onClose={() => setConfirming(null)}>
          <ErrorAlert error={deleteError} />
          <p>
            Deleting a category cannot be undone. It only works while the category is empty — the
            server refuses if any guide, wiki page or sub-category is still filed under it.
          </p>
          <div className="page-actions">
            <button
              className="button button--danger"
              type="button"
              disabled={busy}
              onClick={() => void remove(confirming)}
            >
              {busy ? 'Deleting…' : 'Delete category'}
            </button>
            <button className="button" type="button" onClick={() => setConfirming(null)}>
              Keep it
            </button>
          </div>
        </Modal>
      )}
    </>
  )
}

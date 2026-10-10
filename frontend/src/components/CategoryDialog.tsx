import { useNavigate } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'

import { possibleParents } from '../domain/category'
import type { Category } from '../domain/types'
import {
  useCreateCategory,
  useDeleteCategory,
  useUpdateCategory,
} from '../queries/categories'
import { CategoryOptions } from './editor/CategoryOptions'
import { AutoTextarea, ErrorAlert, Modal } from './ui'

interface CategoryDialogProps {
  categories: Category[]
  /** The category being edited; omitted to create one. */
  category?: Category
  onClose: () => void
}

/**
 * Creates or edits a category. Admin only — the server enforces that; the
 * buttons that open this are simply not drawn for anyone else.
 */
export function CategoryDialog({ categories, category, onClose }: CategoryDialogProps) {
  const navigate = useNavigate()
  const create = useCreateCategory()
  const update = useUpdateCategory()
  const remove = useDeleteCategory()

  const [name, setName] = useState(category?.name ?? '')
  const [description, setDescription] = useState(category?.description ?? '')
  const [parentId, setParentId] = useState(category?.parentId ?? '')
  const [isHidden, setIsHidden] = useState(category?.isHidden ?? false)

  const busy = create.isPending || update.isPending || remove.isPending
  const error = create.error ?? update.error ?? remove.error

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    const fields = {
      name: name.trim(),
      description: description.trim(),
      parentId: parentId || null,
      isHidden,
    }

    if (category) {
      update.mutate(
        { id: category.id, changes: fields },
        {
          onSuccess: (saved) => {
            /* The slug follows the name, and the slug is the URL. */
            if (saved.slug !== category.slug) {
              void navigate({ to: '/c/$slug', params: { slug: saved.slug }, replace: true })
            }
            onClose()
          },
        },
      )
    } else {
      create.mutate(fields, { onSuccess: onClose })
    }
  }

  function onDelete() {
    if (!category) return
    if (!window.confirm(`Delete the category “${category.name}”?`)) return
    remove.mutate(category.id, {
      onSuccess: () => {
        void navigate({ to: '/' })
        onClose()
      },
    })
  }

  return (
    <Modal title={category ? 'Edit category' : 'New category'} onClose={onClose}>
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
          <AutoTextarea
            id="category-description"
            className="textarea"
            rows={2}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="category-parent">
            Inside
          </label>
          <select
            id="category-parent"
            className="select"
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
          >
            <option value="">Top level</option>
            <CategoryOptions categories={possibleParents(categories, category?.id ?? null)} />
          </select>
        </div>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={isHidden}
            onChange={(event) => setIsHidden(event.target.checked)}
          />
          <span>Hide from browsing</span>
        </label>
        <span className="field__hint" style={{ display: 'block', marginBottom: '1rem' }}>
          A hidden category holds guides that are reached through tags. Its guides can still be
          searched and read; it just is not listed.
        </span>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={busy}>
            {category ? 'Save' : 'Create category'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
          {category && (
            <button
              className="button button--danger"
              type="button"
              disabled={busy}
              onClick={onDelete}
            >
              Delete
            </button>
          )}
        </div>
      </form>
    </Modal>
  )
}

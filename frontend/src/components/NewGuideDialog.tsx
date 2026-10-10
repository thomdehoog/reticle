import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'

import { useApi } from '../api/context'
import { categoryQueries } from '../queries/categories'
import { useCreateGuide } from '../queries/guides'
import { CategoryOptions } from './editor/CategoryOptions'
import { ErrorAlert, Modal } from './ui'

/**
 * Creating a guide asks for the two things that cannot be defaulted — a title
 * and where it belongs — then drops the author straight into the editor.
 * Everything else is filled in while writing, which is the point: starting a
 * guide should take one click from anywhere in the app.
 */
export function NewGuideDialog({ onClose }: { onClose: () => void }) {
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories = [] } = useQuery(categoryQueries.list(api))
  const create = useCreateGuide()

  const [title, setTitle] = useState('')
  const [categoryId, setCategoryId] = useState('')

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { title: title.trim(), categoryId },
      {
        onSuccess: (guide) => {
          void navigate({ to: '/g/$id/edit', params: { id: guide.id } })
          onClose()
        },
      },
    )
  }

  return (
    <Modal title="New guide" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={create.error} />

        <div className="field">
          <label className="field__label" htmlFor="new-guide-title">
            Title
          </label>
          <input
            id="new-guide-title"
            className="input"
            required
            value={title}
            placeholder="e.g. Starting up the Leica Stellaris 5"
            onChange={(event) => setTitle(event.target.value)}
          />
          <span className="field__hint">You can change this at any time.</span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="new-guide-category">
            Category
          </label>
          <select
            id="new-guide-category"
            className="select"
            required
            value={categoryId}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="" disabled>
              Choose a category…
            </option>
            <CategoryOptions categories={categories} />
          </select>
        </div>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={create.isPending}>
            {create.isPending ? 'Creating…' : 'Create and start writing'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

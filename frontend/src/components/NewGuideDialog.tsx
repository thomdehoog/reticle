import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { useApi } from '../auth/AuthContext'
import { useCategories } from '../hooks/useCategories'
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
  const { data: categories } = useCategories()

  const [title, setTitle] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const guide = await api.createGuide(title.trim(), categoryId)
      navigate(`/g/${guide.id}/edit`)
      onClose()
    } catch (cause) {
      setError(cause)
      setSubmitting(false)
    }
  }

  return (
    <Modal title="New guide" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={error} />

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
            {(categories ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create and start writing'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

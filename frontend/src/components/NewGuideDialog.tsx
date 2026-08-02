/**
 * The small window that appears when you start a new guide.
 *
 * It asks for the two things a guide cannot exist without - a title and which
 * category it belongs to - then creates it and drops the author straight into
 * the editor. Everything else is filled in while writing.
 *
 * Asking for the minimum is deliberate. A long form in front of somebody who has
 * just had an idea is how the idea gets lost, and starting a guide should take
 * one click from anywhere in the application.
 */

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { useCategories } from '../hooks/useCategories'
import { ErrorAlert, Modal } from './ui'

export function NewGuideDialog({ onClose }: { onClose: () => void }) {
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories, error: categoriesError } = useCategories()

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
        {/* An empty category list is not "no categories yet", it is a request
            that failed — and the form below cannot be completed without one. */}
        <ErrorAlert error={error ?? categoriesError} />

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

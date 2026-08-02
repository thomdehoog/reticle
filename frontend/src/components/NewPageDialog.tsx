import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { useCategories } from '../hooks/useCategories'
import { ErrorAlert, Modal } from './ui'

/**
 * Starting a wiki page.
 *
 * The landing-page checkbox is here rather than only in the editor because
 * that is the decision an author has already made — they are writing the
 * Confocal page, not a page they will later attach to Confocal — and the server
 * refuses a second landing page for the same category, so making the choice up
 * front is where that answer is cheapest to act on.
 */
export function NewPageDialog({ onClose }: { onClose: () => void }) {
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories } = useCategories()

  const [title, setTitle] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [isLanding, setIsLanding] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      const page = await api.createPage({
        title: title.trim(),
        categoryId: categoryId === '' ? null : categoryId,
        isLanding: categoryId !== '' && isLanding,
      })
      navigate(`/w/${page.id}/edit`)
      onClose()
    } catch (cause) {
      setError(cause)
      setSubmitting(false)
    }
  }

  return (
    <Modal title="New page" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={error} />

        <div className="field">
          <label className="field__label" htmlFor="new-page-title">
            Title
          </label>
          <input
            id="new-page-title"
            className="input"
            required
            value={title}
            placeholder="e.g. Choosing an objective"
            onChange={(event) => setTitle(event.target.value)}
          />
          <span className="field__hint">You can change this at any time.</span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="new-page-category">
            Category
          </label>
          <select
            id="new-page-category"
            className="select"
            value={categoryId}
            onChange={(event) => setCategoryId(event.target.value)}
          >
            <option value="">Standalone article</option>
            {(categories ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        </div>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={isLanding}
            disabled={categoryId === ''}
            onChange={(event) => setIsLanding(event.target.checked)}
          />
          <span>This is the category&rsquo;s landing page</span>
        </label>
        <span className="field__hint">
          The landing page is what people see when they open the category, instead of a bare list of
          guides.
        </span>

        <div className="page-actions" style={{ marginTop: '1.25rem' }}>
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

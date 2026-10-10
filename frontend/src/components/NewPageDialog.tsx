import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState, type FormEvent } from 'react'

import { useApi } from '../api/context'
import { categoryQueries } from '../queries/categories'
import { useCreatePage } from '../queries/pages'
import { CategoryOptions } from './editor/CategoryOptions'
import { ErrorAlert, Modal } from './ui'

interface NewPageDialogProps {
  onClose: () => void
  /**
   * Set when the page is being written as a category's landing page: the
   * category is then fixed and its name offered as the title.
   */
  landingFor?: { id: string; name: string }
}

/** The wiki counterpart of `NewGuideDialog`: a title, a place, then the editor. */
export function NewPageDialog({ onClose, landingFor }: NewPageDialogProps) {
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories = [] } = useQuery(categoryQueries.list(api))
  const create = useCreatePage()

  const [title, setTitle] = useState(landingFor?.name ?? '')
  const [categoryId, setCategoryId] = useState(landingFor?.id ?? '')

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { title: title.trim(), categoryId: categoryId || null, isLanding: landingFor !== undefined },
      {
        onSuccess: (page) => {
          void navigate({ to: '/w/$id/edit', params: { id: page.id } })
          onClose()
        },
      },
    )
  }

  return (
    <Modal title={landingFor ? 'New landing page' : 'New wiki page'} onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={create.error} />

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

        {!landingFor && (
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
              <CategoryOptions categories={categories} />
            </select>
          </div>
        )}

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

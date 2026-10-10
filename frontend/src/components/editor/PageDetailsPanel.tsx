import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useRef } from 'react'

import { useApi } from '../../api/context'
import { IMAGE_ACCEPT } from '../../domain/media'
import { MAX_ALT_LENGTH, type Category, type Page } from '../../domain/types'
import { useUploadMedia } from '../../queries/media'
import { pageQueries } from '../../queries/pages'
import { AutoTextarea } from '../ui'
import { CategoryOptions } from './CategoryOptions'

interface PageDetailsPanelProps {
  page: Page
  categories: Category[]
  onChange: (mutator: (page: Page) => Page) => void
  onError: (error: unknown) => void
}

/** A wiki page's title, summary, hero image, and its place among the categories. */
export function PageDetailsPanel({ page, categories, onChange, onError }: PageDetailsPanelProps) {
  const api = useApi()
  const upload = useUploadMedia()
  const heroRef = useRef<HTMLInputElement>(null)

  /* A category has one landing page, and the server answers a second with the
     same `conflict` it uses for a lost save — which the editor would then
     report as a colleague's edit. So the question is asked here first, and the
     box is simply not offered while another page holds the place. */
  const { data: currentLanding } = useQuery({
    ...pageQueries.landing(api, page.categoryId ?? ''),
    enabled: page.categoryId !== null,
  })
  const takenBy =
    page.categoryId !== null && currentLanding && currentLanding.id !== page.id
      ? currentLanding
      : null

  async function onPickHero(file: File | undefined) {
    if (!file) return
    onError(null)
    try {
      const media = await upload.mutateAsync({ file })
      /* A new picture is not described by the words written for the old one. */
      onChange((current) => ({ ...current, heroMediaId: media.id, heroAlt: '' }))
    } catch (cause) {
      onError(cause)
    }
  }

  return (
    <aside className="editor__sidebar">
      <div className="card">
        <div className="card__body">
          <div className="field">
            <label className="field__label" htmlFor="page-title">
              Title
            </label>
            <input
              id="page-title"
              className="input"
              value={page.title}
              onChange={(event) => onChange((current) => ({ ...current, title: event.target.value }))}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="page-summary">
              Summary
            </label>
            <AutoTextarea
              id="page-summary"
              className="textarea"
              rows={2}
              value={page.summary}
              onChange={(event) =>
                onChange((current) => ({ ...current, summary: event.target.value }))
              }
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="page-category">
              Category
            </label>
            <select
              id="page-category"
              className="select"
              value={page.categoryId ?? ''}
              onChange={(event) => {
                const categoryId = event.target.value || null
                /* "Landing page" means landing page *of this category*, so it
                   does not follow the page to a new one: the new category may
                   have its own already, and a page with none cannot be one at
                   all. The author ticks the box again if that is the intent. */
                onChange((current) => ({ ...current, categoryId, isLanding: false }))
              }}
            >
              <option value="">Standalone article</option>
              <CategoryOptions categories={categories} />
            </select>
          </div>

          <label className="checkbox">
            <input
              type="checkbox"
              checked={page.isLanding}
              disabled={page.categoryId === null || (takenBy !== null && !page.isLanding)}
              onChange={(event) =>
                onChange((current) => ({ ...current, isLanding: event.target.checked }))
              }
            />
            <span>Use as this category&rsquo;s landing page</span>
          </label>
          <span className="field__hint">
            The landing page is what people see when they open the category, instead of a bare list
            of guides.
          </span>
          {takenBy && (
            <span className="field__hint" style={{ display: 'block', marginTop: '0.4rem' }}>
              This category already has one:{' '}
              <Link to="/w/$id/edit" params={{ id: takenBy.id }}>
                {takenBy.title || 'Untitled page'}
              </Link>
              .
            </span>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="field" style={{ marginBottom: 0 }}>
            <span className="field__label">Hero image</span>
            {page.heroMediaId && (
              /* Described by the field below, which is right next to it; an
                 alt here would have a screen reader say the same words twice. */
              <img
                className="hero-preview"
                src={api.mediaDisplayUrl(page.heroMediaId)}
                alt=""
                decoding="async"
              />
            )}
            <div className="page-actions">
              <button
                type="button"
                className="button button--sm"
                disabled={upload.isPending}
                onClick={() => heroRef.current?.click()}
              >
                {upload.isPending ? 'Uploading…' : page.heroMediaId ? 'Replace' : 'Choose image'}
              </button>
              {page.heroMediaId && (
                <button
                  type="button"
                  className="button button--sm"
                  onClick={() =>
                    onChange((current) => ({ ...current, heroMediaId: null, heroAlt: '' }))
                  }
                >
                  Remove
                </button>
              )}
            </div>
            <input
              ref={heroRef}
              type="file"
              accept={IMAGE_ACCEPT}
              aria-label="Upload a hero image"
              hidden
              onChange={(event) => {
                void onPickHero(event.target.files?.[0])
                event.target.value = ''
              }}
            />
            <span className="field__hint">Shown across the top of the page, above the text.</span>
          </div>

          {page.heroMediaId && (
            <div className="field" style={{ marginTop: '0.9rem', marginBottom: 0 }}>
              <label className="field__label" htmlFor="page-hero-alt">
                Describe this image
              </label>
              <AutoTextarea
                id="page-hero-alt"
                className="textarea"
                rows={2}
                maxLength={MAX_ALT_LENGTH}
                value={page.heroAlt}
                onChange={(event) =>
                  onChange((current) => ({ ...current, heroAlt: event.target.value }))
                }
              />
              <span className="field__hint">
                Read aloud to people who cannot see the picture. Leave it empty if the image is
                only decoration.
              </span>
            </div>
          )}
        </div>
      </div>
    </aside>
  )
}

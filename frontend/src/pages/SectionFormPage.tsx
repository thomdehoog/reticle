/**
 * Writing a section: its title, its words, and its picture.
 *
 * A page rather than a dialog, because this is where a section is *composed*
 * and a modal is a shape for confirming something. It is also the only screen
 * an administrator needs for the job — creating one and editing one are the
 * same three fields, so they are the same component, told apart by whether a
 * section was handed to it.
 *
 * **The words and the picture are the landing page's.** A section keeps them
 * there rather than on its own row, which is where the migration put them and
 * where every screen already reads them from: the tile that opens a section,
 * the banner across the top of it, and the card beside a search result all go
 * through the same fallback. Writing them onto the category instead would have
 * left every imported section opening this form with three empty fields beside
 * a tile that plainly shows all three.
 *
 * So a section that has never had a landing page gets one the moment it is
 * given words or a picture, and the form is the only route to it — which is
 * what let the "Edit landing page" button at the foot of a section come out.
 * The page's own title is kept level with the section's name, because nothing
 * shows it separately and two names for one thing is how they drift.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { useState, type FormEvent } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { useApi } from '../auth/AuthContext'
import { Thumbnail } from '../components/Thumbnail'
import { ErrorAlert, Spinner } from '../components/ui'
import type { Category, Page } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

export function SectionFormPage() {
  const { id } = useParams()
  const [search] = useSearchParams()
  const api = useApi()

  const { data, error, loading } = useAsync(async () => {
    if (!id) return { category: null, landing: null }
    const categories = await api.listCategories()
    const category = categories.find((candidate) => candidate.id === id) ?? null
    if (!category) return { category: null, landing: null }
    const landing = await api.getCategoryLandingPage(category.id).catch(() => null)
    return { category, landing }
  }, [api, id])

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (id && !data?.category) return <ErrorAlert error={new Error('No section with that address.')} />

  /* Keyed on the section, so arriving at a different one rebuilds the fields
     rather than showing the section before last's words. */
  return (
    <SectionForm
      key={data?.category?.id ?? 'new'}
      category={data?.category ?? null}
      landing={data?.landing ?? null}
      /* Which section the plus tile was pressed in. Only read when making one:
         moving an existing section between parents is the categories admin
         screen's job, and two screens offering the same move is how a tree ends
         up rearranged by somebody who meant to rename something. */
      parentId={search.get('parent')}
    />
  )
}

function SectionForm({
  category,
  landing,
  parentId,
}: {
  category: Category | null
  landing: Page | null
  parentId: string | null
}) {
  const api = useApi()
  const navigate = useNavigate()

  const [title, setTitle] = useState(category?.name ?? '')
  const [text, setText] = useState(landing?.summary ?? '')
  const [mediaId, setMediaId] = useState<string | null>(landing?.heroMediaId ?? null)
  const [pictureUrl, setPictureUrl] = useState<string | null>(category?.imageUrl ?? null)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)

  async function onPickPicture(file: File | null) {
    if (!file) return
    setUploading(true)
    setFailure(null)
    try {
      const media = await api.uploadMedia(file)
      setMediaId(media.id)
      setPictureUrl(media.url)
    } catch (cause) {
      setFailure(cause)
    } finally {
      setUploading(false)
    }
  }

  /**
   * The landing page is written only when there is something to put on it.
   *
   * A section with no words and no picture should not be given an empty
   * document it never asked for — that is a row nobody edits and a draft
   * sitting in every listing of unfinished work.
   */
  async function saveTheWordsAndThePicture(section: Category) {
    const wanted = text.trim() !== '' || mediaId !== null
    if (!landing && !wanted) return

    const page =
      landing ??
      (await api.createPage({ title: section.name, categoryId: section.id, isLanding: true }))

    const saved = await api.savePage({
      ...page,
      title: section.name,
      summary: text.trim(),
      heroMediaId: mediaId,
    })

    /* A landing page nobody has published is a landing page whose words a
       reader never sees, and the reader is the whole point of them. */
    if (saved.status !== 'published') await api.publishPage(saved.id)
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFailure(null)
    try {
      const section = category
        ? await api.updateCategory(category.id, { name: title.trim() })
        : await api.createCategory({ name: title.trim(), parentId })
      await saveTheWordsAndThePicture(section)
      navigate(`/c/${section.slug}`)
    } catch (cause) {
      setFailure(cause)
      setSaving(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>{category ? `Edit ${category.name}` : 'New section'}</h1>
        </div>
      </div>

      <form className="section-form" onSubmit={onSubmit}>
        <ErrorAlert error={failure} />

        <div className="field">
          <label className="field__label" htmlFor="section-title">
            Title
          </label>
          <input
            id="section-title"
            className="input"
            required
            autoFocus
            value={title}
            placeholder="e.g. Electron Microscopy"
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="section-text">
            Text
          </label>
          <textarea
            id="section-text"
            className="input"
            rows={4}
            value={text}
            placeholder="Two or three sentences, shown across the top of the section."
            onChange={(event) => setText(event.target.value)}
          />
          <span className="field__hint">
            This is the paragraph under the section's name on its own page. Two or three sentences
            is the budget — the platform this replaces put five lines here and nobody read past the
            second visit.
          </span>
        </div>

        <div className="field">
          <span className="field__label">Picture</span>
          <div className="hero-picker">
            <Thumbnail
              seed={title || 'New section'}
              src={pictureUrl}
              className="hero-picker__preview"
            />
            <div className="hero-picker__controls">
              <input
                type="file"
                accept="image/*"
                onChange={(event) => void onPickPicture(event.target.files?.[0] ?? null)}
              />
              {pictureUrl && (
                <button
                  className="button"
                  type="button"
                  onClick={() => {
                    setMediaId(null)
                    setPictureUrl(null)
                  }}
                >
                  Remove
                </button>
              )}
              {uploading && <span className="save-state">Uploading…</span>}
            </div>
          </div>
          <span className="field__hint">
            Browsing is done by eye. Without a picture the section is shown as a drawn figure made
            from its name, which is recognisable but says nothing about the instrument.
          </span>
        </div>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={saving || uploading}>
            {saving ? 'Saving…' : category ? 'Save changes' : 'Create section'}
          </button>
          <button
            className="button"
            type="button"
            onClick={() => navigate(category ? `/c/${category.slug}` : '/')}
          >
            Cancel
          </button>
        </div>
      </form>
    </>
  )
}

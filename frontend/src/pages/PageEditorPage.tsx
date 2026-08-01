import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useApi } from '../auth/AuthContext'
import { LifecycleActions } from '../components/editor/LifecycleActions'
import { RevisionHistory } from '../components/editor/RevisionHistory'
import { TagInput } from '../components/editor/TagInput'
import { IconHistory } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { AutoTextarea, ErrorAlert, Modal, Spinner, StatusBadge } from '../components/ui'
import type { Page } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { useCategories } from '../hooks/useCategories'

const AUTOSAVE_DELAY_MS = 1200

type SaveState = 'clean' | 'pending' | 'saving' | 'saved' | 'error'

const SAVE_LABELS: Record<SaveState, string> = {
  clean: 'All changes saved',
  pending: 'Unsaved changes…',
  saving: 'Saving…',
  saved: 'All changes saved',
  error: 'Could not save',
}

/**
 * The wiki editor.
 *
 * Markdown with a toolbar and a live preview, rather than a WYSIWYG surface.
 * The trade is deliberate: a rich-text editor that stores HTML would put
 * arbitrary markup into the database and force a sanitiser to stand between
 * every author and every reader for ever. Here the stored form is text, the
 * renderer decides what may exist, and the preview means nobody has to imagine
 * the result.
 */
export function PageEditorPage() {
  const { id = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories } = useCategories()
  const { data: loaded, error: loadError, loading } = useAsync(() => api.getPage(id), [api, id])

  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const dirtyRef = useRef(false)

  const [page, setPage] = useState<Page | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [saveError, setSaveError] = useState<unknown>(null)
  const [publishing, setPublishing] = useState(false)
  const [insertingList, setInsertingList] = useState(false)
  const [showingHistory, setShowingHistory] = useState(false)
  const [uploadingHero, setUploadingHero] = useState(false)
  const heroInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (loaded) setPage(loaded)
  }, [loaded])

  const mutate = useCallback((mutator: (current: Page) => Page) => {
    setPage((current) => (current ? mutator(current) : current))
    dirtyRef.current = true
    setSaveState('pending')
  }, [])

  useEffect(() => {
    if (!page || !dirtyRef.current) return

    const timer = setTimeout(async () => {
      dirtyRef.current = false
      setSaveState('saving')
      setSaveError(null)
      try {
        const saved = await api.savePage(page)
        setPage((current) =>
          current && dirtyRef.current
            ? { ...current, updatedAt: saved.updatedAt, version: saved.version, status: saved.status, slug: saved.slug }
            : saved,
        )
        setSaveState(dirtyRef.current ? 'pending' : 'saved')
      } catch (cause) {
        dirtyRef.current = true
        setSaveError(cause)
        setSaveState('error')
      }
    }, AUTOSAVE_DELAY_MS)

    return () => clearTimeout(timer)
  }, [page, api])

  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirtyRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  /** Wraps the selection, or inserts a placeholder when nothing is selected. */
  function wrap(before: string, after: string, placeholder: string) {
    const textarea = bodyRef.current
    if (!textarea || !page) return

    const { selectionStart, selectionEnd, value } = textarea
    const selected = value.slice(selectionStart, selectionEnd) || placeholder
    const next = value.slice(0, selectionStart) + before + selected + after + value.slice(selectionEnd)

    mutate((current) => ({ ...current, body: next }))
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(selectionStart + before.length, selectionStart + before.length + selected.length)
    })
  }

  function insertBlock(block: string) {
    const textarea = bodyRef.current
    if (!textarea || !page) return

    const { selectionStart, value } = textarea
    const needsLeadingBreak = selectionStart > 0 && !value.slice(0, selectionStart).endsWith('\n\n')
    const insertion = `${needsLeadingBreak ? '\n\n' : ''}${block}\n\n`
    const next = value.slice(0, selectionStart) + insertion + value.slice(selectionStart)

    mutate((current) => ({ ...current, body: next }))
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(selectionStart + insertion.length, selectionStart + insertion.length)
    })
  }

  /**
   * The hero is stored as an id, not as a copy of the image, so the picture
   * stays one uploaded file that annotations and steps could also reference.
   */
  async function onPickHero(file: File) {
    setUploadingHero(true)
    setSaveError(null)
    try {
      const uploaded = await api.uploadMedia(file)
      mutate((current) => ({ ...current, heroMediaId: uploaded.id }))
    } catch (cause) {
      setSaveError(cause)
    } finally {
      setUploadingHero(false)
    }
  }

  async function onUnpublish() {
    if (!page) return
    const updated = await api.unpublishPage(page.id)
    dirtyRef.current = false
    setPage(updated)
    setSaveState('saved')
  }

  async function onArchive() {
    if (!page) return
    await api.archivePage(page.id)
    dirtyRef.current = false
    navigate('/')
  }

  async function onPublish() {
    if (!page) return
    if (page.title.trim() === '') {
      setSaveError(new Error('A page needs a title before it can be published.'))
      return
    }

    setPublishing(true)
    setSaveError(null)
    try {
      const saved = await api.savePage(page)
      dirtyRef.current = false
      const published = await api.publishPage(saved.id)
      setPage(published)
      setSaveState('saved')
      navigate(`/w/${published.slug}`)
    } catch (cause) {
      setSaveError(cause)
      setSaveState('error')
    } finally {
      setPublishing(false)
    }
  }

  if (loading) return <Spinner />
  if (loadError) return <ErrorAlert error={loadError} />
  if (!page) return null

  const conflicted = saveError instanceof ApiError && saveError.code === 'conflict'

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <nav className="breadcrumb">
            <Link to="/">Guides</Link>
            <span className="breadcrumb__sep">/</span>
            <span>Editing page</span>
          </nav>
          <h1>{page.title || 'Untitled page'}</h1>
        </div>
        <div className="page-actions">
          <StatusBadge status={page.status} />
          <span className={`save-state${saveState === 'error' ? ' save-state--error' : ''}`}>
            {SAVE_LABELS[saveState]}
          </span>
          {page.status === 'published' && (
            <Link className="button" to={`/w/${page.slug}`}>
              View
            </Link>
          )}
          <button className="button" type="button" onClick={() => setShowingHistory(true)}>
            <IconHistory />
            History
          </button>
          <LifecycleActions
            kind="page"
            status={page.status}
            onUnpublish={onUnpublish}
            onArchive={onArchive}
          />
          <button
            className="button button--primary"
            type="button"
            onClick={() => void onPublish()}
            disabled={publishing}
          >
            {publishing ? 'Publishing…' : page.status === 'published' ? 'Publish update' : 'Publish'}
          </button>
        </div>
      </div>

      {showingHistory && (
        <RevisionHistory
          title="Published versions"
          list={() => api.listPageRevisions(page.id)}
          load={(version) => api.getPageRevision(page.id, version)}
          render={(snapshot) => (
            <>
              <h3>{snapshot.title}</h3>
              <MarkdownBody body={snapshot.body} />
            </>
          )}
          onClose={() => setShowingHistory(false)}
        />
      )}

      {conflicted ? (
        <div className="alert alert--warning" role="alert">
          <strong>Someone else saved this page while you were editing.</strong> Your recent changes
          have not been saved, so their work is intact.{' '}
          <button className="button button--sm" type="button" onClick={() => window.location.reload()}>
            Reload their version
          </button>
        </div>
      ) : (
        <ErrorAlert error={saveError} />
      )}

      <div className="editor">
        <div>
          <div className="wiki-toolbar">
            <button type="button" className="button button--sm" onClick={() => insertBlock('## Heading')}>
              Heading
            </button>
            <button type="button" className="button button--sm" onClick={() => wrap('**', '**', 'bold text')}>
              Bold
            </button>
            <button type="button" className="button button--sm" onClick={() => wrap('_', '_', 'italic text')}>
              Italic
            </button>
            <button type="button" className="button button--sm" onClick={() => insertBlock('- First item\n- Second item')}>
              List
            </button>
            <button type="button" className="button button--sm" onClick={() => wrap('[', '](https://)', 'link text')}>
              Link
            </button>
            <button type="button" className="button button--sm" onClick={() => insertBlock('| Column | Column |\n| --- | --- |\n| Value | Value |')}>
              Table
            </button>
            <button type="button" className="button button--sm button--primary" onClick={() => setInsertingList(true)}>
              Insert guide list
            </button>
          </div>

          <div className="wiki-split">
            {/* A plain textarea, not the auto-growing one: a wiki body can run
                to thousands of words, and a box that grows without limit makes
                the preview beside it unreachable. */}
            <textarea
              ref={bodyRef}
              className="textarea wiki-source"
              value={page.body}
              placeholder="Write the page here. Use the buttons above if you would rather not type markup."
              onChange={(event) => mutate((current) => ({ ...current, body: event.target.value }))}
            />
            <div className="wiki-preview">
              <span className="wiki-preview__label">Preview</span>
              <MarkdownBody body={page.body} />
            </div>
          </div>
        </div>

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
                  onChange={(event) => mutate((current) => ({ ...current, title: event.target.value }))}
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
                  onChange={(event) => mutate((current) => ({ ...current, summary: event.target.value }))}
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
                  onChange={(event) =>
                    mutate((current) => ({ ...current, categoryId: event.target.value || null }))
                  }
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
                  checked={page.isLanding}
                  disabled={page.categoryId === null}
                  onChange={(event) =>
                    mutate((current) => ({ ...current, isLanding: event.target.checked }))
                  }
                />
                <span>Use as this category&rsquo;s landing page</span>
              </label>
              <span className="field__hint">
                The landing page is what people see when they open the category, instead of a bare
                list of guides.
              </span>

              <div className="field" style={{ marginTop: '1rem', marginBottom: 0 }}>
                <span className="field__label">Hero image</span>
                {page.heroMediaId ? (
                  <div className="hero-picker">
                    <img src={`/api/media/${page.heroMediaId}`} alt="" />
                    <div className="hero-picker__actions">
                      <button
                        className="button button--sm"
                        type="button"
                        onClick={() => heroInputRef.current?.click()}
                      >
                        Replace
                      </button>
                      <button
                        className="button button--sm button--danger"
                        type="button"
                        onClick={() => mutate((current) => ({ ...current, heroMediaId: null }))}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    className="button button--sm"
                    type="button"
                    disabled={uploadingHero}
                    onClick={() => heroInputRef.current?.click()}
                  >
                    {uploadingHero ? 'Uploading…' : 'Choose an image'}
                  </button>
                )}
                <input
                  ref={heroInputRef}
                  type="file"
                  aria-label="Hero image"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  hidden
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    event.target.value = ''
                    if (file) void onPickHero(file)
                  }}
                />
                <span className="field__hint">
                  Shown above the page. One picture of the instrument or the room is worth more here
                  than a paragraph describing which door to use.
                </span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {insertingList && (
        <GuideListDialog
          onClose={() => setInsertingList(false)}
          onInsert={(block) => {
            insertBlock(block)
            setInsertingList(false)
          }}
        />
      )}
    </>
  )
}

/** Builds a guide-list block so an author never types the fenced syntax. */
function GuideListDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void
  onInsert: (block: string) => void
}) {
  const [tags, setTags] = useState<string[]>([])
  const [heading, setHeading] = useState('')
  const [limit, setLimit] = useState('')

  function build(): string {
    const lines = ['```guidelist', `tags: ${tags.join(', ')}`]
    if (heading.trim() !== '') lines.push(`heading: ${heading.trim()}`)
    const capped = Number.parseInt(limit, 10)
    if (Number.isFinite(capped) && capped > 0) lines.push(`limit: ${capped}`)
    lines.push('```')
    return lines.join('\n')
  }

  return (
    <Modal title="Insert a guide list" onClose={onClose}>
      <p className="field__hint" style={{ marginBottom: '1rem' }}>
        A guide list gathers every published guide carrying the tags you choose, and keeps itself up
        to date as guides are added.
      </p>

      <div className="field">
        <span className="field__label">Tags</span>
        <TagInput tags={tags} onChange={setTags} />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="guidelist-heading">
          Heading (optional)
        </label>
        <input
          id="guidelist-heading"
          className="input"
          value={heading}
          placeholder="e.g. Confocal systems"
          onChange={(event) => setHeading(event.target.value)}
        />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="guidelist-limit">
          Show at most (optional)
        </label>
        <input
          id="guidelist-limit"
          className="input"
          type="number"
          min={1}
          value={limit}
          placeholder="every matching guide"
          onChange={(event) => setLimit(event.target.value)}
        />
        <span className="field__hint">
          For a &ldquo;recently added&rdquo; block on a busy page. Leave it empty and the list keeps
          showing everything that carries the tags.
        </span>
      </div>

      <div className="page-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={tags.length === 0}
          onClick={() => onInsert(build())}
        >
          Insert
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

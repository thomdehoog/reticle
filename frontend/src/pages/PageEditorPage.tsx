/**
 * The screen where a wiki page is written.
 *
 * The wiki counterpart of the guide editor. A wiki page is one body of text
 * rather than numbered steps, so this is much simpler - but it saves the same
 * way, refuses to overwrite a colleague's changes the same way, and publishes the
 * same way.
 *
 * Wiki pages can also embed a live list of guides carrying a given tag, so a
 * "Confocal" page always lists every confocal guide without anybody maintaining
 * the list by hand.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useApi } from '../auth/AuthContext'
import { LifecycleActions } from '../components/editor/LifecycleActions'
import { RevisionHistory } from '../components/editor/RevisionHistory'
import { SaveConflict } from '../components/editor/SaveConflict'
import { TagInput } from '../components/editor/TagInput'
import { IconHistory } from '../components/icons'
import { MarkdownBody } from '../components/MarkdownBody'
import { AutoTextarea, ErrorAlert, Modal, Spinner, StatusBadge } from '../components/ui'
import type { Page } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import {
  forgetFailedSave,
  readFailedSave,
  rememberFailedSave,
  useAutosave,
} from '../hooks/useAutosave'
import { useCategories } from '../hooks/useCategories'

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
  const { data: categories, error: categoriesError } = useCategories()
  const { data: loaded, error: loadError, loading } = useAsync(() => api.getPage(id), [api, id])

  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const dirtyRef = useRef(false)

  const [page, setPage] = useState<Page | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [saveError, setSaveError] = useState<unknown>(null)
  /** The server's copy, fetched once a save is refused, so a choice can be offered. */
  const [conflict, setConflict] = useState<Page | null>(null)
  /** Left by a save that failed after the editor had already closed. */
  const [failedSaveNote, setFailedSaveNote] = useState(() => readFailedSave(id))
  const [publishing, setPublishing] = useState(false)
  const [insertingList, setInsertingList] = useState(false)
  const [showingHistory, setShowingHistory] = useState(false)
  const [uploadingHero, setUploadingHero] = useState(false)
  const heroInputRef = useRef<HTMLInputElement>(null)

  // Seeding the editable copy from what the server returned. This is the
  // legitimate case the `set-state-in-effect` rule carves out - state
  // synchronised from outside React - and it cannot be derived during render,
  // because from the first keystroke the local copy is the newer of the two and
  // recomputing it would discard what the author just typed.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (loaded) setPage(loaded)
  }, [loaded])

  const mutate = useCallback((mutator: (current: Page) => Page) => {
    setPage((current) => (current ? mutator(current) : current))
    dirtyRef.current = true
    setSaveState('pending')
  }, [])

  const saveNow = useCallback(async () => {
    if (!page) return
    dirtyRef.current = false
    setSaveState('saving')
    setSaveError(null)
    try {
      const saved = await api.savePage(page)
      setPage((current) =>
        current && dirtyRef.current
          ? {
              ...current,
              updatedAt: saved.updatedAt,
              version: saved.version,
              status: saved.status,
              slug: saved.slug,
            }
          : saved,
      )
      setSaveState(dirtyRef.current ? 'pending' : 'saved')
      forgetFailedSave(page.id)
      setFailedSaveNote(null)
    } catch (cause) {
      dirtyRef.current = true
      setSaveError(cause)
      setSaveState('error')
      /* This same function performs the save fired as the editor closes, and
         that one has no screen left to report on. The note is what the author
         is shown the next time they open this page. */
      rememberFailedSave(page.id, cause instanceof Error ? cause.message : 'Something went wrong.')

      /* A refused write leaves this copy holding the `updatedAt` the server
         rejected, so every later autosave would carry it and be refused too.
         Their copy is what a choice can be offered between; if fetching it
         fails as well, the plain error stays and says so. */
      if (cause instanceof ApiError && cause.code === 'conflict') {
        setConflict(await api.getPage(page.id).catch(() => null))
      }
    }
  }, [page, api])

  useAutosave({
    snapshot: page,
    // An unresolved conflict is waiting for the author to choose. Saving again
    // before they do would re-send the rejected write once per pause.
    isDirty: () => dirtyRef.current && conflict === null,
    save: () => void saveNow(),
  })

  function keepMyVersion() {
    if (!conflict) return
    /* Adopting their timestamp is what makes the next write legal. It replaces
       their text with this one, which is the choice just made. */
    setPage((current) => (current ? { ...current, updatedAt: conflict.updatedAt } : current))
    dirtyRef.current = true
    setSaveState('pending')
    setSaveError(null)
    setConflict(null)
  }

  function useTheirVersion() {
    if (!conflict) return
    setPage(conflict)
    dirtyRef.current = false
    setSaveState('saved')
    setSaveError(null)
    setConflict(null)
    forgetFailedSave(conflict.id)
    setFailedSaveNote(null)
  }

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
    /* Claimed before awaiting, as in onPublish: a pending autosave that fired
       during the await would carry the timestamp this call is about to move on. */
    dirtyRef.current = false
    const updated = await api.unpublishPage(page.id)
    setPage(updated)
    setSaveState('saved')
  }

  async function onArchive() {
    if (!page) return
    dirtyRef.current = false
    await api.archivePage(page.id)
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
      dirtyRef.current = false
      const saved = await api.savePage(page)
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
          {/* Announced, not just drawn: with no Save button this line is the
              only answer to "did that save", and a blind author has no other. */}
          <span
            className={`save-state${saveState === 'error' ? ' save-state--error' : ''}`}
            role="status"
          >
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

      {failedSaveNote && (
        <div className="alert alert--warning" role="alert">
          <strong>Your last change to this page did not save.</strong> {failedSaveNote} What you see
          below is the copy on the server, so anything typed after that is not in it.{' '}
          <button
            className="button button--sm"
            type="button"
            onClick={() => {
              forgetFailedSave(id)
              setFailedSaveNote(null)
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      {conflict ? (
        <SaveConflict
          kind="page"
          savedBy={conflict.lastEditedBy.displayName}
          savedAt={conflict.updatedAt}
          myVersion={[page.title, '', page.body].join('\n').trim()}
          onKeepMine={keepMyVersion}
          onUseTheirs={useTheirVersion}
        />
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
                {/* An empty list here is not "no categories", it is a failed
                    request — and a page silently becomes a standalone article. */}
                <ErrorAlert error={categoriesError} />
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

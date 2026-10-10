import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useId, useLayoutEffect, useRef, useState, type ClipboardEvent, type DragEvent, type KeyboardEvent } from 'react'

import { useApi } from '../../api/context'
import { useSession } from '../../auth/session'
import { insertImage, type TextEdit } from '../../domain/markdownEdit'
import { mediaKindOf, stepMediaProblem } from '../../domain/media'
import type { Page } from '../../domain/types'
import { useAutosave } from '../../hooks/useAutosave'
import { useDocumentActions } from '../../hooks/useDocumentActions'
import { useLeaveGuard } from '../../hooks/useLeaveGuard'
import { categoryQueries } from '../../queries/categories'
import {
  pageQueries,
  useArchivePage,
  usePublishPage,
  useRevertPage,
  useSavePage,
  useUnpublishPage,
} from '../../queries/pages'
import { useUploadLimits } from '../../queries/config'
import { useUploadMedia } from '../../queries/media'
import { CategoryCrumbs, Crumb } from '../CategoryCrumbs'
import { MarkdownBody } from '../MarkdownBody'
import { EditorAlerts } from './EditorAlerts'
import { EditorHeader } from './EditorHeader'
import { BOLD, ITALIC, LINK, MarkdownToolbar, type BodyEdit } from './MarkdownToolbar'
import { PageDetailsPanel } from './PageDetailsPanel'

/** The server's publish rules for a page, checked here so the reason is immediate. */
function publishIssues(page: Page): string[] {
  const issues: string[] = []
  if (page.title.trim() === '') {
    issues.push('A page needs a title before it can be published.')
  }
  if (page.body.trim() === '') {
    issues.push('A page needs some content before it can be published.')
  }
  return issues
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
export function PageEditor({ initial }: { initial: Page }) {
  const api = useApi()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { can } = useSession()
  const { data: categories = [] } = useQuery(categoryQueries.list(api))

  const save = useSavePage()
  const publish = usePublishPage()
  const unpublish = useUnpublishPage()
  const revert = useRevertPage()
  const archive = useArchivePage()

  const autosave = useAutosave({ initial, save: save.mutateAsync })
  const page = autosave.document
  useLeaveGuard(autosave)

  const bodyRef = useRef<HTMLTextAreaElement>(null)
  /* Once a publish has been refused, the list of reasons follows the page as
     it is edited: each one disappears as it is dealt with, instead of going on
     accusing a page that has since been fixed. */
  const [checking, setChecking] = useState(false)
  const issues = checking ? publishIssues(page) : []

  const actions = useDocumentActions({
    autosave,
    readyToPublish: () => {
      setChecking(true)
      return publishIssues(page).length === 0
    },
    publish: publish.mutateAsync,
    unpublish: unpublish.mutateAsync,
    revert: revert.mutateAsync,
    archive: (current) => archive.mutateAsync(current),
    onPublished: (published) =>
      void navigate({ to: '/w/$slug', params: { slug: published.slug } }),
    onDiscarded: (restored) => {
      setChecking(false)
      return restored
    },
    onArchived: () => void navigate({ to: '/' }),
    archiveWarning:
      'Archive this page? It disappears for everyone, including authors. The content is kept ' +
      'on the server, but bringing it back needs an administrator with database access.',
    discardWarning: (version) =>
      `Discard every change made to this page since version ${version} was published? ` +
      'The editor goes back to that version — the one readers see. This cannot be undone.',
  })

  /**
   * Which of the two panes shows where there is only room for one. On a wide
   * screen both are visible side by side and this does nothing.
   */
  const [pane, setPane] = useState<'write' | 'preview'>('write')
  const paneId = useId()

  /**
   * Applies a toolbar edit to the body, then puts the cursor where the edit
   * says once React has written the new text into the textarea.
   */
  function editBody(compute: BodyEdit) {
    const textarea = bodyRef.current
    if (!textarea) return

    const edit = compute(textarea.value, textarea.selectionStart, textarea.selectionEnd)
    pendingSelection.current = edit
    autosave.change((current) => ({ ...current, body: edit.value }))
    /* A formatting button pressed while reading the preview acts on the
       source, so the source is what should be showing afterwards. */
    setPane('write')
  }

  /**
   * Restores the cursor once the edited text is actually in the textarea.
   *
   * Tied to the render that writes it rather than to a timer or an animation
   * frame: an edit made after an upload finishes is rendered a moment later
   * than one made from a click, and a selection set before the new text
   * arrives is thrown away when it does — the cursor lands at the very end.
   */
  const pendingSelection = useRef<TextEdit | null>(null)
  useLayoutEffect(() => {
    const textarea = bodyRef.current
    const pending = pendingSelection.current
    if (!textarea || !pending || pending.value !== page.body) return
    pendingSelection.current = null
    textarea.focus()
    textarea.setSelectionRange(pending.selectionStart, pending.selectionEnd)
  }, [page.body, pane])

  const upload = useUploadMedia()
  const limits = useUploadLimits()
  const [uploading, setUploading] = useState<number | null>(null)

  /**
   * An image goes into the body as ordinary Markdown pointing at the upload.
   * The server reads those references on save, which is what later lets a
   * viewer fetch the picture once the page is published.
   */
  async function placeImage(file: File) {
    autosave.reportError(null)
    const problem =
      mediaKindOf(file) === 'image'
        ? stepMediaProblem(file, limits)
        : `“${file.name}” is not a picture. A wiki page takes PNG, JPEG, WebP or GIF images.`
    if (problem) {
      autosave.reportError(new Error(problem))
      return
    }

    setUploading(0)
    try {
      const media = await upload.mutateAsync({
        file,
        onProgress: ({ loaded, total }) => setUploading(total > 0 ? loaded / total : 0),
      })
      const alt = file.name.replace(/\.[^.]+$/, '')
      editBody((value, start) => insertImage(value, start, alt, media.url))
    } catch (cause) {
      autosave.reportError(cause)
    } finally {
      setUploading(null)
    }
  }

  /* Screenshots arrive by paste and by drag far more often than through a
     file dialog, so the source box takes both. Anything that is not a file is
     left to the textarea's own handling. */
  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const file = Array.from(event.clipboardData.files).find(
      (candidate) => mediaKindOf(candidate) === 'image',
    )
    if (!file) return
    event.preventDefault()
    void placeImage(file)
  }

  function onDrop(event: DragEvent<HTMLTextAreaElement>) {
    const file = event.dataTransfer.files[0]
    if (!file) return
    event.preventDefault()
    void placeImage(file)
  }

  function onShortcut(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (!(event.ctrlKey || event.metaKey) || event.altKey || event.shiftKey) return
    const edit = { b: BOLD, i: ITALIC, k: LINK }[event.key.toLowerCase()]
    if (!edit) return
    event.preventDefault()
    editBody(edit)
  }

  async function reloadFromServer() {
    try {
      const fresh = await queryClient.fetchQuery({
        ...pageQueries.detail(api, page.id),
        staleTime: 0,
      })
      autosave.reset(fresh)
      setChecking(false)
    } catch (cause) {
      autosave.reportError(cause)
    }
  }

  return (
    <>
      <EditorHeader
        breadcrumb={
          <CategoryCrumbs
            categories={categories}
            categoryId={page.categoryId}
            root={page.categoryId === null ? <Link to="/wiki">Wiki</Link> : undefined}
          >
            <Crumb>
              <span>Editing page</span>
            </Crumb>
          </CategoryCrumbs>
        }
        title={page.title || 'Untitled page'}
        status={page.status}
        version={page.version}
        hasUnpublishedChanges={page.hasUnpublishedChanges}
        saveState={autosave.saveState}
        busy={actions.busy}
        canArchive={can('admin')}
        viewLink={
          <Link className="button" to="/w/$slug" params={{ slug: page.slug }}>
            View
          </Link>
        }
        historyLink={
          <Link className="button" to="/w/$slug/history" params={{ slug: page.slug }}>
            History
          </Link>
        }
        onPublish={actions.publish}
        onUnpublish={actions.unpublish}
        onDiscard={actions.discard}
        onArchive={actions.archive}
      />

      <EditorAlerts
        noun="page"
        error={autosave.error}
        conflicted={autosave.conflicted}
        onReload={() => void reloadFromServer()}
        issues={issues}
      />

      <div className="editor">
        <div>
          <MarkdownToolbar onEdit={editBody} onImage={(file) => void placeImage(file)} uploading={uploading} />

          {/* Drawn only where the two panes do not fit side by side. */}
          <div className="wiki-tabs" role="tablist" aria-label="Editor view">
            <button
              type="button"
              role="tab"
              id={`${paneId}-write-tab`}
              aria-selected={pane === 'write'}
              aria-controls={`${paneId}-write`}
              onClick={() => setPane('write')}
            >
              Write
            </button>
            <button
              type="button"
              role="tab"
              id={`${paneId}-preview-tab`}
              aria-selected={pane === 'preview'}
              aria-controls={`${paneId}-preview`}
              onClick={() => setPane('preview')}
            >
              Preview
            </button>
          </div>

          <div className={`wiki-split wiki-split--${pane}`}>
            {/* A plain textarea, not the auto-growing one: a wiki body can run
                to thousands of words, and a box that grows without limit makes
                the preview beside it unreachable. */}
            <textarea
              ref={bodyRef}
              id={`${paneId}-write`}
              className="textarea wiki-source"
              aria-label="Page content (Markdown)"
              value={page.body}
              placeholder="Write the page here. Use the buttons above if you would rather not type markup, and paste or drop a picture to add it."
              onChange={(event) =>
                autosave.change((current) => ({ ...current, body: event.target.value }))
              }
              onKeyDown={onShortcut}
              onPaste={onPaste}
              onDrop={onDrop}
            />
            <section className="wiki-preview" id={`${paneId}-preview`} aria-label="Preview">
              <span className="wiki-preview__label" aria-hidden="true">
                Preview
              </span>
              {page.body.trim() === '' ? (
                <p className="wiki-preview__empty">Nothing to preview yet.</p>
              ) : (
                <MarkdownBody body={page.body} />
              )}
            </section>
          </div>
        </div>

        <PageDetailsPanel
          page={page}
          categories={categories}
          onChange={autosave.change}
          onError={autosave.reportError}
        />
      </div>
    </>
  )
}

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useRef, useState } from 'react'

import { useApi } from '../../api/context'
import { useSession } from '../../auth/session'
import { insertBlock, wrapSelection, type TextEdit } from '../../domain/markdownEdit'
import type { Page } from '../../domain/types'
import { useAutosave } from '../../hooks/useAutosave'
import { useDocumentActions } from '../../hooks/useDocumentActions'
import { useLeaveGuard } from '../../hooks/useLeaveGuard'
import { categoryQueries } from '../../queries/categories'
import {
  pageQueries,
  useArchivePage,
  usePublishPage,
  useSavePage,
  useUnpublishPage,
} from '../../queries/pages'
import { MarkdownBody } from '../MarkdownBody'
import { EditorAlerts } from './EditorAlerts'
import { EditorHeader } from './EditorHeader'
import { MarkdownToolbar } from './MarkdownToolbar'
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
  const archive = useArchivePage()

  const autosave = useAutosave({ initial, save: save.mutateAsync })
  const page = autosave.document
  useLeaveGuard(autosave)

  const bodyRef = useRef<HTMLTextAreaElement>(null)
  const [issues, setIssues] = useState<string[]>([])

  const actions = useDocumentActions({
    autosave,
    readyToPublish: () => {
      const found = publishIssues(page)
      setIssues(found)
      return found.length === 0
    },
    publish: publish.mutateAsync,
    unpublish: unpublish.mutateAsync,
    archive: (current) => archive.mutateAsync(current),
    onPublished: (published) =>
      void navigate({ to: '/w/$slug', params: { slug: published.slug } }),
    onArchived: () => void navigate({ to: '/' }),
    archiveWarning:
      'Archive this page? It disappears for everyone, including authors. The content is kept ' +
      'on the server, but bringing it back needs an administrator with database access.',
  })

  /**
   * Applies a toolbar edit to the body, then puts the cursor where the edit
   * says once React has written the new text into the textarea.
   */
  function editBody(compute: (value: string, start: number, end: number) => TextEdit) {
    const textarea = bodyRef.current
    if (!textarea) return

    const edit = compute(textarea.value, textarea.selectionStart, textarea.selectionEnd)
    autosave.change((current) => ({ ...current, body: edit.value }))
    requestAnimationFrame(() => {
      textarea.focus()
      textarea.setSelectionRange(edit.selectionStart, edit.selectionEnd)
    })
  }

  async function reloadFromServer() {
    try {
      const fresh = await queryClient.fetchQuery({
        ...pageQueries.detail(api, page.id),
        staleTime: 0,
      })
      autosave.reset(fresh)
      setIssues([])
    } catch (cause) {
      autosave.reportError(cause)
    }
  }

  return (
    <>
      <EditorHeader
        crumb="Editing page"
        title={page.title || 'Untitled page'}
        status={page.status}
        saveState={autosave.saveState}
        busy={actions.busy}
        canArchive={can('admin')}
        viewLink={
          <Link className="button" to="/w/$slug" params={{ slug: page.slug }}>
            View
          </Link>
        }
        onPublish={actions.publish}
        onUnpublish={actions.unpublish}
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
          <MarkdownToolbar
            onWrap={(before, after, placeholder) =>
              editBody((value, start, end) =>
                wrapSelection(value, start, end, before, after, placeholder),
              )
            }
            onInsertBlock={(block) => editBody((value, start) => insertBlock(value, start, block))}
            onError={autosave.reportError}
          />

          <div className="wiki-split">
            {/* A plain textarea, not the auto-growing one: a wiki body can run
                to thousands of words, and a box that grows without limit makes
                the preview beside it unreachable. */}
            <textarea
              ref={bodyRef}
              className="textarea wiki-source"
              aria-label="Page content (Markdown)"
              value={page.body}
              placeholder="Write the page here. Use the buttons above if you would rather not type markup."
              onChange={(event) =>
                autosave.change((current) => ({ ...current, body: event.target.value }))
              }
            />
            <div className="wiki-preview">
              <span className="wiki-preview__label">Preview</span>
              <MarkdownBody body={page.body} />
            </div>
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

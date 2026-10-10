import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useRef, useState } from 'react'

import { useApi } from '../../api/context'
import { useSession } from '../../auth/session'
import {
  createStep,
  renumberSteps,
  validateForPublish,
} from '../../domain/guide'
import type { Guide } from '../../domain/types'
import { useAutosave } from '../../hooks/useAutosave'
import { useDocumentActions } from '../../hooks/useDocumentActions'
import { useLeaveGuard } from '../../hooks/useLeaveGuard'
import { categoryQueries } from '../../queries/categories'
import {
  guideQueries,
  useArchiveGuide,
  usePublishGuide,
  useRevertGuide,
  useSaveGuide,
  useUnpublishGuide,
} from '../../queries/guides'
import { useUploadLimits } from '../../queries/config'
import { CategoryCrumbs, Crumb } from '../CategoryCrumbs'
import { EditorAlerts } from './EditorAlerts'
import { EditorHeader } from './EditorHeader'
import { GuideDetailsPanel } from './GuideDetailsPanel'
import { StepList } from './StepList'
import { StepNavigator } from './StepNavigator'

/**
 * A guide straight from "New guide" has no steps at all, and an editor with
 * nothing in it but an "Add step" button is a poor welcome. It opens on one
 * empty step instead. That step exists only on screen until the author types —
 * it is not an edit, so nothing is saved on its account.
 */
function withFirstStep(guide: Guide): Guide {
  return guide.steps.length > 0 ? guide : { ...guide, steps: renumberSteps([createStep()]) }
}

/**
 * The guide editor.
 *
 * `initial` seeds the author's working copy and is then ignored: from the first
 * keystroke the copy on screen is newer than anything the server has, and it is
 * the autosave — not a refetch — that reconciles the two.
 */
export function GuideEditor({ initial }: { initial: Guide }) {
  const api = useApi()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { can } = useSession()
  const { data: categories = [] } = useQuery(categoryQueries.list(api))

  const save = useSaveGuide()
  const publish = usePublishGuide()
  const unpublish = useUnpublishGuide()
  const revert = useRevertGuide()
  const archive = useArchiveGuide()

  const [seed] = useState(() => withFirstStep(initial))
  const autosave = useAutosave({ initial: seed, save: save.mutateAsync })
  const guide = autosave.document
  useLeaveGuard(autosave)

  /* Once a publish has been refused, the list of reasons follows the guide as
     it is edited: each one disappears as it is dealt with, instead of going on
     accusing a guide that has since been fixed. */
  const [checking, setChecking] = useState(false)
  const { maxMediaPerStep } = useUploadLimits()
  const issues = checking ? validateForPublish(guide, maxMediaPerStep) : []
  const stepsRef = useRef<HTMLDivElement>(null)

  const actions = useDocumentActions({
    autosave,
    readyToPublish: () => {
      setChecking(true)
      return validateForPublish(guide, maxMediaPerStep).length === 0
    },
    publish: publish.mutateAsync,
    unpublish: unpublish.mutateAsync,
    revert: revert.mutateAsync,
    archive: (current) => archive.mutateAsync(current),
    onPublished: (published) =>
      void navigate({ to: '/g/$slug', params: { slug: published.slug } }),
    onDiscarded: (restored) => {
      setChecking(false)
      return withFirstStep(restored)
    },
    onArchived: () => void navigate({ to: '/' }),
    archiveWarning:
      'Archive this guide? It disappears for everyone, including authors. The content is kept ' +
      'on the server, but bringing it back needs an administrator with database access.',
    discardWarning: (version) =>
      `Discard every change made to this guide since version ${version} was published? ` +
      'The editor goes back to that version — the one readers see. This cannot be undone.',
  })

  /** After a conflict: take the colleague's version, discarding the local copy. */
  async function reloadFromServer() {
    try {
      const fresh = await queryClient.fetchQuery({
        ...guideQueries.detail(api, guide.id),
        staleTime: 0,
      })
      autosave.reset(withFirstStep(fresh))
      setChecking(false)
    } catch (cause) {
      autosave.reportError(cause)
    }
  }

  return (
    <>
      <EditorHeader
        breadcrumb={
          <CategoryCrumbs categories={categories} categoryId={guide.categoryId}>
            <Crumb>
              <span>Editing</span>
            </Crumb>
          </CategoryCrumbs>
        }
        title={guide.title || 'Untitled guide'}
        status={guide.status}
        version={guide.version}
        hasUnpublishedChanges={guide.hasUnpublishedChanges}
        saveState={autosave.saveState}
        busy={actions.busy}
        canArchive={can('admin')}
        viewLink={
          <Link className="button" to="/g/$slug" params={{ slug: guide.slug }}>
            View
          </Link>
        }
        historyLink={
          <Link className="button" to="/g/$slug/history" params={{ slug: guide.slug }}>
            History
          </Link>
        }
        onPublish={actions.publish}
        onUnpublish={actions.unpublish}
        onDiscard={actions.discard}
        onArchive={actions.archive}
      />

      <EditorAlerts
        noun="guide"
        error={autosave.error}
        conflicted={autosave.conflicted}
        onReload={() => void reloadFromServer()}
        issues={issues.map((issue) => issue.message)}
      />

      <div className="editor editor--with-nav">
        <StepNavigator
          steps={guide.steps}
          stepsContainer={stepsRef}
          onReorder={(steps) => autosave.change((current) => ({ ...current, steps }))}
        />

        <StepList
          steps={guide.steps}
          containerRef={stepsRef}
          onChange={(mutator) =>
            autosave.change((current) => ({ ...current, steps: mutator(current.steps) }))
          }
        />

        <GuideDetailsPanel guide={guide} categories={categories} onChange={autosave.change} />
      </div>
    </>
  )
}

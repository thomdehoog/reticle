/**
 * The screen where a guide is written.
 *
 * This is the biggest screen in the application and the one that has to be
 * trusted most, because somebody is putting real work into it. It holds the
 * guide's title and summary, its tags, and every step with its points and
 * pictures.
 *
 * It saves by itself, a couple of seconds after you stop typing, so there is no
 * Save button to forget. It also refuses to overwrite somebody else's changes: if
 * a colleague edited the same guide while this copy was open, saving stops and
 * says so rather than quietly discarding their work.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useApi } from '../auth/AuthContext'
import { BulletList } from '../components/BulletList'
import { LifecycleActions } from '../components/editor/LifecycleActions'
import { RevisionHistory } from '../components/editor/RevisionHistory'
import { StepEditor } from '../components/editor/StepEditor'
import { StepNavigator } from '../components/editor/StepNavigator'
import { TagInput } from '../components/editor/TagInput'
import { IconHistory, IconPlus } from '../components/icons'
import { StepGallery } from '../components/StepGallery'
import { AutoTextarea, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import {
  DIFFICULTY_LABELS,
  DIFFICULTY_ORDER,
  createStep,
  insertStepAfter,
  moveStep,
  removeStep,
  renumberSteps,
  validateForPublish,
  type ValidationIssue,
} from '../domain/guide'
import { MAX_MEDIA_PER_STEP, type Difficulty, type Guide } from '../domain/types'
import { useAsync } from '../hooks/useAsync'
import { useAutosave } from '../hooks/useAutosave'
import { useCategories } from '../hooks/useCategories'

type SaveState = 'clean' | 'pending' | 'saving' | 'saved' | 'error'

const SAVE_LABELS: Record<SaveState, string> = {
  clean: 'All changes saved',
  pending: 'Unsaved changes…',
  saving: 'Saving…',
  saved: 'All changes saved',
  error: 'Could not save',
}

export function GuideEditorPage() {
  const { id = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories } = useCategories()
  const { data: loaded, error: loadError, loading } = useAsync(() => api.getGuide(id), [api, id])

  const [guide, setGuide] = useState<Guide | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [saveError, setSaveError] = useState<unknown>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [focusBulletId, setFocusBulletId] = useState<string | null>(null)
  const [uploadingStepId, setUploadingStepId] = useState<string | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [publishing, setPublishing] = useState(false)
  const [showingHistory, setShowingHistory] = useState(false)

  const dirtyRef = useRef(false)
  const stepsRef = useRef<HTMLDivElement>(null)

  // Seeding the editable copy from what the server returned. This is the
  // legitimate case the `set-state-in-effect` rule carves out - state
  // synchronised from outside React - and it cannot be derived during render,
  // because from the first keystroke the local copy is the newer of the two and
  // recomputing it would discard what the author just typed.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (loaded) setGuide(loaded)
  }, [loaded])

  const mutate = useCallback((mutator: (current: Guide) => Guide) => {
    setGuide((current) => (current ? mutator(current) : current))
    dirtyRef.current = true
    setSaveState('pending')
  }, [])

  /**
   * Autosave. The write carries the `updatedAt` we last saw, so if a colleague
   * saved the same guide in the meantime the server answers `conflict` and we
   * stop rather than overwriting their work.
   */
  const saveNow = useCallback(async () => {
    if (!guide) return
    dirtyRef.current = false
    setSaveState('saving')
    setSaveError(null)

    try {
      const saved = await api.saveGuide(guide)
      setGuide((current) =>
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
    } catch (cause) {
      dirtyRef.current = true
      setSaveError(cause)
      setSaveState('error')
    }
  }, [guide, api])

  useAutosave({
    document: guide,
    isDirty: () => dirtyRef.current,
    save: () => void saveNow(),
  })

  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirtyRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  /**
   * The server decides from the bytes whether an upload is a picture or a clip,
   * so the answer comes back on `kind` rather than being guessed from the file
   * name here. A clip takes the step's single video slot; a second one replaces
   * the first, which is the only sensible reading of dropping one onto a step
   * that already has one.
   */
  async function onUpload(stepId: string, files: File[]) {
    setUploadingStepId(stepId)
    setSaveError(null)
    try {
      const uploaded = await Promise.all(files.map((file) => api.uploadMedia(file)))
      const images = uploaded.filter((item) => item.kind === 'image')
      const clips = uploaded.filter((item) => item.kind === 'video')

      mutate((current) => ({
        ...current,
        steps: current.steps.map((step) =>
          step.id === stepId
            ? {
                ...step,
                media: [...step.media, ...images].slice(0, MAX_MEDIA_PER_STEP),
                video: clips.length > 0 ? clips[clips.length - 1] : step.video,
              }
            : step,
        ),
      }))
    } catch (cause) {
      setSaveError(cause)
    } finally {
      setUploadingStepId(null)
    }
  }

  async function onUnpublish() {
    if (!guide) return
    const updated = await api.unpublishGuide(guide.id)
    dirtyRef.current = false
    setGuide(updated)
    setSaveState('saved')
  }

  async function onArchive() {
    if (!guide) return
    await api.archiveGuide(guide.id)
    dirtyRef.current = false
    /* Home rather than back to the guide: the guide is gone from every listing
       the editor could return to, and its own URL now 404s. */
    navigate('/')
  }

  async function onPublish() {
    if (!guide) return

    const found = validateForPublish(guide)
    setIssues(found)
    if (found.length > 0) return

    setPublishing(true)
    setSaveError(null)
    // Claim the work before awaiting. The autosave timer may already be
    // running; if it fires while this save is in flight it would send a second
    // write carrying the same expectedUpdatedAt, and one of the two would come
    // back as a conflict - telling an author working alone that somebody else
    // had edited their guide.
    dirtyRef.current = false
    try {
      const saved = await api.saveGuide(guide)
      const published = await api.publishGuide(saved.id)
      setGuide(published)
      setSaveState('saved')
      navigate(`/g/${published.slug}`)
    } catch (cause) {
      setSaveError(cause)
      setSaveState('error')
    } finally {
      setPublishing(false)
    }
  }

  if (loading) return <Spinner />
  if (loadError) return <ErrorAlert error={loadError} />
  if (!guide) return null

  const conflicted = saveError instanceof ApiError && saveError.code === 'conflict'

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <nav className="breadcrumb">
            <Link to="/">Guides</Link>
            <span className="breadcrumb__sep">/</span>
            <span>Editing</span>
          </nav>
          <h1>{guide.title || 'Untitled guide'}</h1>
        </div>
        <div className="page-actions">
          <StatusBadge status={guide.status} />
          <span className={`save-state${saveState === 'error' ? ' save-state--error' : ''}`}>
            {SAVE_LABELS[saveState]}
          </span>
          {guide.status === 'published' && (
            <Link className="button" to={`/g/${guide.slug}`}>
              View
            </Link>
          )}
          <button className="button" type="button" onClick={() => setShowingHistory(true)}>
            <IconHistory />
            History
          </button>
          <LifecycleActions
            kind="guide"
            status={guide.status}
            onUnpublish={onUnpublish}
            onArchive={onArchive}
          />
          <button
            className="button button--primary"
            type="button"
            onClick={() => void onPublish()}
            disabled={publishing}
          >
            {publishing ? 'Publishing…' : guide.status === 'published' ? 'Publish update' : 'Publish'}
          </button>
        </div>
      </div>

      {showingHistory && (
        <RevisionHistory
          title="Published versions"
          list={() => api.listGuideRevisions(guide.id)}
          load={(version) => api.getGuideRevision(guide.id, version)}
          render={(snapshot) => (
            <>
              <h3>{snapshot.title}</h3>
              {snapshot.introduction && <p>{snapshot.introduction}</p>}
              {snapshot.steps.map((step, index) => (
                <div className="revisions__step" key={step.id}>
                  <h3>
                    Step {index + 1}
                    {step.title ? `: ${step.title}` : ''}
                  </h3>
                  <StepGallery step={step} />
                  <BulletList bullets={step.bullets} />
                </div>
              ))}
              {snapshot.conclusion && <p>{snapshot.conclusion}</p>}
            </>
          )}
          onClose={() => setShowingHistory(false)}
        />
      )}

      {conflicted ? (
        <div className="alert alert--warning" role="alert">
          <strong>Someone else saved this guide while you were editing.</strong> To avoid
          overwriting their work, your recent changes have not been saved.{' '}
          <button className="button button--sm" type="button" onClick={() => window.location.reload()}>
            Reload their version
          </button>
        </div>
      ) : (
        <ErrorAlert error={saveError} />
      )}

      {issues.length > 0 && (
        <div className="alert alert--warning" role="alert">
          <strong>This guide is not ready to publish:</strong>
          <ul style={{ margin: '0.4rem 0 0', paddingLeft: '1.2rem' }}>
            {issues.map((issue) => (
              <li key={issue.field}>{issue.message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="editor editor--with-nav">
        <StepNavigator
          steps={guide.steps}
          stepsContainer={stepsRef}
          onReorder={(steps) => mutate((current) => ({ ...current, steps }))}
        />

        <div ref={stepsRef}>
          {guide.steps.map((step, index) => (
            <StepEditor
              key={step.id}
              step={step}
              number={index + 1}
              isFirst={index === 0}
              isLast={index === guide.steps.length - 1}
              canRemove={guide.steps.length > 1}
              focusBulletId={focusBulletId}
              uploading={uploadingStepId === step.id}
              dragging={dragIndex === index}
              dropTarget={dragIndex !== null && dragIndex !== index}
              onChange={(updated) =>
                mutate((current) => ({
                  ...current,
                  steps: current.steps.map((candidate) =>
                    candidate.id === step.id ? updated : candidate,
                  ),
                }))
              }
              onRemove={() =>
                mutate((current) => ({ ...current, steps: removeStep(current.steps, index) }))
              }
              onMove={(delta) =>
                mutate((current) => ({
                  ...current,
                  steps: moveStep(current.steps, index, index + delta),
                }))
              }
              onFocusBullet={setFocusBulletId}
              onUpload={(files) => void onUpload(step.id, files)}
              onDragStart={() => setDragIndex(index)}
              onDragEnter={() => {
                if (dragIndex === null || dragIndex === index) return
                mutate((current) => ({
                  ...current,
                  steps: moveStep(current.steps, dragIndex, index),
                }))
                setDragIndex(index)
              }}
              onDragEnd={() => setDragIndex(null)}
            />
          ))}

          <button
            className="button"
            type="button"
            onClick={() =>
              mutate((current) => ({
                ...current,
                steps:
                  current.steps.length === 0
                    ? renumberSteps([createStep()])
                    : insertStepAfter(current.steps, current.steps.length - 1),
              }))
            }
          >
            <IconPlus />
            Add step
          </button>
        </div>

        <aside className="editor__sidebar">
          <div className="card">
            <div className="card__body">
              <div className="field">
                <label className="field__label" htmlFor="guide-title">
                  Title
                </label>
                <input
                  id="guide-title"
                  className="input"
                  value={guide.title}
                  onChange={(event) => mutate((current) => ({ ...current, title: event.target.value }))}
                />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="guide-category">
                  Category
                </label>
                <select
                  id="guide-category"
                  className="select"
                  value={guide.categoryId}
                  onChange={(event) =>
                    mutate((current) => ({ ...current, categoryId: event.target.value }))
                  }
                >
                  {(categories ?? []).map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <span className="field__label">Tags</span>
                <TagInput
                  tags={guide.tags}
                  onChange={(tags) => mutate((current) => ({ ...current, tags }))}
                />
                <span className="field__hint">
                  Tags decide where this guide appears. A wiki page can gather every guide
                  carrying a tag, so one guide can show up under several instruments.
                </span>
              </div>

              <div className="field">
                <label className="field__label" htmlFor="guide-summary">
                  Summary
                </label>
                <AutoTextarea
                  id="guide-summary"
                  className="textarea"
                  rows={2}
                  value={guide.summary}
                  placeholder="One line shown in listings."
                  onChange={(event) =>
                    mutate((current) => ({ ...current, summary: event.target.value }))
                  }
                />
              </div>

              <div className="field">
                <label className="field__label" htmlFor="guide-difficulty">
                  Difficulty
                </label>
                <select
                  id="guide-difficulty"
                  className="select"
                  value={guide.difficulty}
                  onChange={(event) =>
                    mutate((current) => ({
                      ...current,
                      difficulty: event.target.value as Difficulty,
                    }))
                  }
                >
                  {DIFFICULTY_ORDER.map((value) => (
                    <option key={value} value={value}>
                      {DIFFICULTY_LABELS[value]}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <span className="field__label">Time required (minutes)</span>
                <div className="field-pair">
                  <input
                    className="input"
                    type="number"
                    min={0}
                    aria-label="Time required, from"
                    placeholder="from"
                    value={guide.timeRequiredMinMinutes ?? ''}
                    onChange={(event) =>
                      mutate((current) => ({
                        ...current,
                        timeRequiredMinMinutes:
                          event.target.value === '' ? null : Number(event.target.value),
                      }))
                    }
                  />
                  <span aria-hidden="true">–</span>
                  <input
                    className="input"
                    type="number"
                    min={0}
                    aria-label="Time required, to"
                    placeholder="to"
                    value={guide.timeRequiredMaxMinutes ?? ''}
                    onChange={(event) =>
                      mutate((current) => ({
                        ...current,
                        timeRequiredMaxMinutes:
                          event.target.value === '' ? null : Number(event.target.value),
                      }))
                    }
                  />
                </div>
                <span className="field__hint">
                  A range is more honest than a single number. Leave the second box empty if it is
                  reliably one duration.
                </span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card__body">
              <div className="field">
                <label className="field__label" htmlFor="guide-intro">
                  Introduction
                </label>
                <AutoTextarea
                  id="guide-intro"
                  className="textarea"
                  rows={4}
                  value={guide.introduction}
                  placeholder="Context, scope, who this is for."
                  onChange={(event) =>
                    mutate((current) => ({ ...current, introduction: event.target.value }))
                  }
                />
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label className="field__label" htmlFor="guide-conclusion">
                  Conclusion
                </label>
                <AutoTextarea
                  id="guide-conclusion"
                  className="textarea"
                  rows={3}
                  value={guide.conclusion}
                  placeholder="Shutdown, clean-up, what to do if it went wrong."
                  onChange={(event) =>
                    mutate((current) => ({ ...current, conclusion: event.target.value }))
                  }
                />
              </div>
            </div>
          </div>
        </aside>
      </div>
    </>
  )
}

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import { useApi } from '../auth/AuthContext'
import { StepEditor } from '../components/editor/StepEditor'
import { TagInput } from '../components/editor/TagInput'
import { IconPlus } from '../components/icons'
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

  const dirtyRef = useRef(false)

  useEffect(() => {
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
  useEffect(() => {
    if (!guide || !dirtyRef.current) return

    const timer = setTimeout(async () => {
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
    }, AUTOSAVE_DELAY_MS)

    return () => clearTimeout(timer)
  }, [guide, api])

  useEffect(() => {
    function warn(event: BeforeUnloadEvent) {
      if (dirtyRef.current) event.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [])

  async function onUpload(stepId: string, files: File[]) {
    setUploadingStepId(stepId)
    setSaveError(null)
    try {
      const uploaded = await Promise.all(files.map((file) => api.uploadMedia(file)))
      mutate((current) => ({
        ...current,
        steps: current.steps.map((step) =>
          step.id === stepId
            ? { ...step, media: [...step.media, ...uploaded].slice(0, MAX_MEDIA_PER_STEP) }
            : step,
        ),
      }))
    } catch (cause) {
      setSaveError(cause)
    } finally {
      setUploadingStepId(null)
    }
  }

  async function onPublish() {
    if (!guide) return

    const found = validateForPublish(guide)
    setIssues(found)
    if (found.length > 0) return

    setPublishing(true)
    setSaveError(null)
    try {
      const saved = await api.saveGuide(guide)
      dirtyRef.current = false
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

      <div className="editor">
        <div>
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

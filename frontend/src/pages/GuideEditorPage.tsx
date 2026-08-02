/**
 * The screen where a guide is written.
 *
 * This is the biggest screen in the application and the one that has to be
 * trusted most, because somebody is putting real work into it. It holds the
 * guide's title and summary, its tags, and every step with its points and
 * pictures.
 *
 * It saves by itself, a couple of seconds after you stop typing, so there is no
 * Save button to forget. It also refuses to overwrite somebody else's changes:
 * if a colleague edited the same guide while this copy was open, the save stops
 * rather than quietly discarding their work, and the author is shown both what
 * they wrote and who else saved, and asked which version wins.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ApiError } from '../api/client'
import { useApi } from '../auth/AuthContext'
import { BulletList } from '../components/BulletList'
import { LifecycleActions } from '../components/editor/LifecycleActions'
import { RevisionHistory } from '../components/editor/RevisionHistory'
import { SaveConflict } from '../components/editor/SaveConflict'
import { StepEditor } from '../components/editor/StepEditor'
import { StepNavigator } from '../components/editor/StepNavigator'
import { TagInput } from '../components/editor/TagInput'
import { IconHistory, IconPlus } from '../components/icons'
import { StepGallery } from '../components/StepGallery'
import { AutoTextarea, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { DIFFICULTY_LABELS, DIFFICULTY_ORDER, createStep, insertStepAfter, moveStep, numberedSteps, removeStep, renumberSteps, type ValidationIssue, validateForPublish } from '../domain/guide'
import { MAX_MEDIA_PER_STEP, type Difficulty, type Guide } from '../domain/types'
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

/** The author's own words, flattened so they can be selected and copied out. */
function guideAsPlainText(guide: Guide): string {
  const lines = [guide.title, guide.summary, guide.introduction, '']

  guide.steps.forEach((step, index) => {
    lines.push(`Step ${index + 1}${step.title ? `: ${step.title}` : ''}`)
    for (const bullet of step.bullets) lines.push(`  • ${bullet.text}`)
    lines.push('')
  })

  return lines.join('\n').trim()
}

export function GuideEditorPage() {
  const { id = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const { data: categories, error: categoriesError } = useCategories()
  const { data: loaded, error: loadError, loading } = useAsync(() => api.getGuide(id), [api, id])

  const [guide, setGuide] = useState<Guide | null>(null)
  const [saveState, setSaveState] = useState<SaveState>('clean')
  const [saveError, setSaveError] = useState<unknown>(null)
  /** The server's copy, fetched once a save is refused, so a choice can be offered. */
  const [conflict, setConflict] = useState<Guide | null>(null)
  /** Left by a save that failed after the editor had already closed. */
  const [failedSaveNote, setFailedSaveNote] = useState(() => readFailedSave(id))
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
      forgetFailedSave(guide.id)
      setFailedSaveNote(null)
    } catch (cause) {
      dirtyRef.current = true
      setSaveError(cause)
      setSaveState('error')
      /* This same function performs the save fired as the editor closes, and
         that one has no screen left to report on. The note is what the author
         is shown the next time they open this guide. */
      rememberFailedSave(guide.id, cause instanceof Error ? cause.message : 'Something went wrong.')

      /* A refused write leaves this copy holding the `updatedAt` the server
         rejected, so every later autosave would carry it and be refused too.
         Their copy is what a choice can be offered between; if fetching it
         fails as well, the plain error stays and says so. */
      if (cause instanceof ApiError && cause.code === 'conflict') {
        setConflict(await api.getGuide(guide.id).catch(() => null))
      }
    }
  }, [guide, api])

  useAutosave({
    snapshot: guide,
    // An unresolved conflict is waiting for the author to choose. Saving again
    // before they do would re-send the rejected write once per pause.
    isDirty: () => dirtyRef.current && conflict === null,
    save: () => void saveNow(),
  })

  function keepMyVersion() {
    if (!conflict) return
    /* Adopting their timestamp is what makes the next write legal. It replaces
       their text with this one, which is the choice just made. */
    setGuide((current) => (current ? { ...current, updatedAt: conflict.updatedAt } : current))
    dirtyRef.current = true
    setSaveState('pending')
    setSaveError(null)
    setConflict(null)
  }

  function takeTheirVersion() {
    if (!conflict) return
    setGuide(conflict)
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
    /* Claimed before awaiting, as in onPublish: a pending autosave that fired
       during the await would carry the timestamp this call is about to move on. */
    dirtyRef.current = false
    const updated = await api.unpublishGuide(guide.id)
    setGuide(updated)
    setSaveState('saved')
  }

  async function onArchive() {
    if (!guide) return
    dirtyRef.current = false
    await api.archiveGuide(guide.id)
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

  /* The same function the reader uses, so an author writing step 7 is looking
     at what a reader will call step 7. */
  const stepNumbers = numberedSteps(guide.steps)

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
          {/* Announced, not just drawn: with no Save button this line is the
              only answer to "did that save", and a blind author has no other. */}
          <span
            className={`save-state${saveState === 'error' ? ' save-state--error' : ''}`}
            role="status"
          >
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
                  <BulletList step={step} />
                </div>
              ))}
            </>
          )}
          onClose={() => setShowingHistory(false)}
        />
      )}

      {failedSaveNote && (
        <div className="alert alert--warning" role="alert">
          <strong>Your last change to this guide did not save.</strong> {failedSaveNote} What you see
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
          kind="guide"
          savedBy={conflict.lastEditedBy.displayName}
          savedAt={conflict.updatedAt}
          myVersion={guideAsPlainText(guide)}
          onKeepMine={keepMyVersion}
          onUseTheirs={takeTheirVersion}
        />
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
          {/* Numbered the way the reader numbers, so an author sees the step
              numbers a reader will see rather than positions in an array. */}
          {guide.steps.map((step, index) => (
            <StepEditor
              key={step.id}
              step={step}
              number={stepNumbers.get(step.id) ?? null}
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
                {/* An empty list here is not "no categories", it is a failed
                    request — and publishing then demands a category the author
                    has no way to choose. */}
                <ErrorAlert error={categoriesError} />
              </div>

              <div className="field">
                <span className="field__label">Tags</span>
                <TagInput
                  tags={guide.tags}
                  onChange={(tags) => mutate((current) => ({ ...current, tags }))}
                />
                {/* Not obvious from the label, and getting it wrong is why a
                    finished guide never appears anywhere. */}
                <span className="field__hint">Tags decide where this guide appears.</span>
              </div>

              {/* Above the tree rather than in it, so it is worth saying what
                  that costs: the quick links are a short list by definition,
                  and a facility that marks thirty of them has a second front
                  page instead of an answer. */}
              <div className="field">
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={guide.isQuickLink}
                    onChange={(event) =>
                      mutate((current) => ({ ...current, isQuickLink: event.target.checked }))
                    }
                  />
                  Show as a quick link
                </label>
                <span className="field__hint">
                  On the front page and on every category, above the sections.
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
                {/* Said once, here, rather than in every bullet's placeholder.
                    The same formatting works in the points on every step, and
                    an author who has read it once does not need telling
                    again. */}
                <p className="field__hint">
                  <strong>**bold**</strong>, <em>_italic_</em> and [text](/g/slug) work here and
                  in every point.
                </p>
              </div>

            </div>
          </div>
        </aside>
      </div>
    </>
  )
}

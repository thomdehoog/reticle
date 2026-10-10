import { useState, type RefObject } from 'react'

import {
  createStep,
  insertStepAfter,
  moveStep,
  removeStep,
  renumberSteps,
} from '../../domain/guide'
import { ApiError } from '../../api/client'
import { stepMediaProblem } from '../../domain/media'
import type { Step } from '../../domain/types'
import { useUploadLimits } from '../../queries/config'
import { useUploadMedia } from '../../queries/media'
import { IconPlus } from '../icons'
import type { UploadStatus } from './MediaSlots'
import { StepEditor } from './StepEditor'

interface StepListProps {
  steps: Step[]
  /** Handed to the step rail, which scrolls to and watches the cards in here. */
  containerRef: RefObject<HTMLDivElement | null>
  /**
   * Takes a function of the current steps rather than a new array: an upload
   * finishes seconds after it started, and must be applied to the steps as they
   * are then, not as they were when the file was dropped.
   */
  onChange: (mutator: (steps: Step[]) => Step[]) => void
}

/**
 * The server's own sentence where it sent one — "Videos may be at most 200 MB"
 * is already written for a person — and something usable where it did not.
 */
function describeUploadFailure(cause: unknown): string {
  if (cause instanceof ApiError) {
    if (cause.code === 'network_error') return 'the connection to the server was lost.'
    return cause.message
  }
  return 'something went wrong.'
}

interface StepUpload extends UploadStatus {
  cancel: () => void
}

/** The column of step cards: editing, reordering, adding, and media uploads. */
export function StepList({ steps, containerRef, onChange }: StepListProps) {
  const upload = useUploadMedia()
  const limits = useUploadLimits()

  const [focusBulletId, setFocusBulletId] = useState<string | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  /* Uploads and their problems are kept per step: a video can take minutes,
     and the author will be working on another step — perhaps adding a picture
     to it — long before it finishes. */
  const [uploads, setUploads] = useState<Record<string, StepUpload>>({})
  const [problems, setProblems] = useState<Record<string, string[]>>({})

  function setStepUpload(stepId: string, next: StepUpload | null) {
    setUploads(({ [stepId]: _previous, ...others }) => (next ? { ...others, [stepId]: next } : others))
  }

  function setStepProblems(stepId: string, next: string[]) {
    setProblems(({ [stepId]: _previous, ...others }) =>
      next.length > 0 ? { ...others, [stepId]: next } : others,
    )
  }

  /**
   * Checks what was dropped, then uploads it one file at a time.
   *
   * One at a time so that a refused file costs only itself: the two pictures
   * that went up before an oversized video stay in the step, and the message
   * names the one that did not. It is also the kinder thing to do to a
   * facility's uplink with three 150 MB clips.
   */
  async function onUpload(stepId: string, files: File[], room: number) {
    const refused: string[] = []
    const accepted: File[] = []
    for (const file of files) {
      const problem = stepMediaProblem(file, limits)
      if (problem) refused.push(problem)
      else accepted.push(file)
    }
    if (accepted.length > room) {
      const dropped = accepted.splice(room)
      refused.push(
        `A step holds ${limits.maxMediaPerStep} images or videos, so ${dropped
          .map((file) => `“${file.name}”`)
          .join(', ')} ${dropped.length === 1 ? 'was' : 'were'} left out.`,
      )
    }
    setStepProblems(stepId, refused)
    if (accepted.length === 0) return

    const controller = new AbortController()
    const total = accepted.reduce((sum, file) => sum + file.size, 0)
    let finished = 0
    const report = (loaded: number) =>
      setStepUpload(stepId, { loaded, total, cancel: () => controller.abort() })
    report(0)

    try {
      for (const file of accepted) {
        try {
          const media = await upload.mutateAsync({
            file,
            signal: controller.signal,
            /* The request body is a little larger than the file — multipart
               framing — so the fraction sent is applied to the file's size. */
            onProgress: (progress) =>
              report(finished + (progress.total > 0 ? progress.loaded / progress.total : 0) * file.size),
          })
          onChange((current) =>
            current.map((step) =>
              step.id === stepId && step.media.length < limits.maxMediaPerStep
                ? { ...step, media: [...step.media, media] }
                : step,
            ),
          )
        } catch (cause) {
          if (cause instanceof ApiError && cause.code === 'cancelled') break
          refused.push(`“${file.name}” was not uploaded: ${describeUploadFailure(cause)}`)
          setStepProblems(stepId, [...refused])
        }
        finished += file.size
        report(finished)
      }
    } finally {
      setStepUpload(stepId, null)
    }
  }

  return (
    <div ref={containerRef}>
      {steps.map((step, index) => (
        <StepEditor
          key={step.id}
          step={step}
          number={index + 1}
          isFirst={index === 0}
          isLast={index === steps.length - 1}
          canRemove={steps.length > 1}
          focusBulletId={focusBulletId}
          upload={uploads[step.id] ?? null}
          problems={problems[step.id] ?? []}
          onCancelUpload={() => uploads[step.id]?.cancel()}
          onDismissProblems={() => setStepProblems(step.id, [])}
          dragging={dragIndex === index}
          dropTarget={dragIndex !== null && dragIndex !== index}
          onChange={(updated) =>
            onChange((current) =>
              current.map((candidate) => (candidate.id === step.id ? updated : candidate)),
            )
          }
          onRemove={() => onChange((current) => removeStep(current, index))}
          onMove={(delta) => onChange((current) => moveStep(current, index, index + delta))}
          onFocusBullet={setFocusBulletId}
          onUpload={(files) =>
            void onUpload(step.id, files, limits.maxMediaPerStep - step.media.length)
          }
          onDragStart={() => setDragIndex(index)}
          onDragEnter={() => {
            if (dragIndex === null || dragIndex === index) return
            onChange((current) => moveStep(current, dragIndex, index))
            setDragIndex(index)
          }}
          onDragEnd={() => setDragIndex(null)}
        />
      ))}

      <button
        className="button"
        type="button"
        onClick={() =>
          onChange((current) =>
            current.length === 0
              ? renumberSteps([createStep()])
              : insertStepAfter(current, current.length - 1),
          )
        }
      >
        <IconPlus />
        Add step
      </button>
    </div>
  )
}

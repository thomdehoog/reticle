import { useState, type RefObject } from 'react'

import {
  createStep,
  insertStepAfter,
  moveStep,
  removeStep,
  renumberSteps,
} from '../../domain/guide'
import { MAX_MEDIA_PER_STEP, type Step } from '../../domain/types'
import { useUploadMedia } from '../../queries/media'
import { IconPlus } from '../icons'
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
  onError: (error: unknown) => void
}

/** The column of step cards: editing, reordering, adding, and image uploads. */
export function StepList({ steps, containerRef, onChange, onError }: StepListProps) {
  const upload = useUploadMedia()

  const [focusBulletId, setFocusBulletId] = useState<string | null>(null)
  const [uploadingStepId, setUploadingStepId] = useState<string | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  async function onUpload(stepId: string, files: File[]) {
    setUploadingStepId(stepId)
    onError(null)
    try {
      const uploaded = await Promise.all(files.map((file) => upload.mutateAsync(file)))
      onChange((current) =>
        current.map((step) =>
          step.id === stepId
            ? { ...step, media: [...step.media, ...uploaded].slice(0, MAX_MEDIA_PER_STEP) }
            : step,
        ),
      )
    } catch (cause) {
      onError(cause)
    } finally {
      setUploadingStepId(null)
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
          uploading={uploadingStepId === step.id}
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
          onUpload={(files) => void onUpload(step.id, files)}
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

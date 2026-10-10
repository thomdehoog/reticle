import { useRef, useState, type DragEvent } from 'react'

import { STEP_MEDIA_ACCEPT } from '../../domain/media'
import { MAX_MEDIA_PER_STEP, type Bullet, type Media } from '../../domain/types'
import { AnnotatedImage } from '../AnnotationOverlay'
import { IconClose, IconEdit, IconImage, IconPalette, IconVideo } from '../icons'
import { AnnotationEditor } from './AnnotationEditor'
import { VideoDetailsDialog } from './VideoDetailsDialog'

/** An upload in flight for this step. `total` is 0 until the browser reports one. */
export interface UploadStatus {
  loaded: number
  total: number
}

interface MediaSlotsProps {
  media: Media[]
  /** The step's bullets, so an annotation can take the colour of the one it illustrates. */
  bullets: Bullet[]
  upload: UploadStatus | null
  /** Why files were refused, or why an upload failed; shown beside the slots. */
  problems: string[]
  onAdd: (files: File[]) => void
  onCancelUpload: () => void
  onDismissProblems: () => void
  onRemove: (mediaId: string) => void
  onUpdate: (media: Media) => void
}

/**
 * The three media slots for a step: pictures, videos, or a mix.
 *
 * Accepts a drop anywhere on the strip as well as a click, because dragging a
 * screenshot straight from the desktop is how people actually add images, and
 * the file picker is the fallback rather than the main path.
 *
 * Nothing is filtered out here. A file of the wrong kind is handed on like any
 * other, so that it can be refused *in words* — silently ignoring a dropped
 * `.avi` leaves the author looking at a slot where nothing happened.
 */
export function MediaSlots({
  media,
  bullets,
  upload,
  problems,
  onAdd,
  onCancelUpload,
  onDismissProblems,
  onRemove,
  onUpdate,
}: MediaSlotsProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [detailsFor, setDetailsFor] = useState<string | null>(null)

  const remaining = MAX_MEDIA_PER_STEP - media.length
  const open = media.find((item) => item.id === detailsFor) ?? null
  const percent =
    upload && upload.total > 0 ? Math.min(100, Math.round((upload.loaded / upload.total) * 100)) : null

  function acceptFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    onAdd(Array.from(files))
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragOver(false)
    if (!upload) acceptFiles(event.dataTransfer.files)
  }

  return (
    <>
      <div
        className="media-slots"
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {media.map((item) =>
          item.kind === 'video' ? (
            <div className="media-slot media-slot--video" key={item.id}>
              {/* Metadata only: enough for the browser to draw a first frame
                  as the thumbnail without fetching the whole clip. */}
              <video src={item.url} preload="metadata" muted playsInline tabIndex={-1} />
              <span className="media-slot__kind">
                <IconVideo size={12} />
                Video
              </span>
              <button
                type="button"
                className="media-slot__action media-slot__annotate"
                aria-label="Describe video"
                title="Preview and describe this video"
                onClick={() => setDetailsFor(item.id)}
              >
                <IconEdit size={12} />
              </button>
              <button
                type="button"
                className="media-slot__action media-slot__remove"
                aria-label="Remove video"
                onClick={() => onRemove(item.id)}
              >
                <IconClose size={12} />
              </button>
            </div>
          ) : (
            <div className="media-slot" key={item.id}>
              <AnnotatedImage src={item.url} alt={item.alt} annotations={item.annotations} />
              <button
                type="button"
                className="media-slot__action media-slot__annotate"
                aria-label="Annotate image"
                title="Draw on this image and describe it"
                onClick={() => setDetailsFor(item.id)}
              >
                <IconPalette size={12} />
              </button>
              <button
                type="button"
                className="media-slot__action media-slot__remove"
                aria-label="Remove image"
                onClick={() => onRemove(item.id)}
              >
                <IconClose size={12} />
              </button>
              {item.annotations.length > 0 && (
                <span
                  className="media-slot__badge"
                  title={`${item.annotations.length} annotation${item.annotations.length === 1 ? '' : 's'}`}
                >
                  {item.annotations.length}
                </span>
              )}
            </div>
          ),
        )}

        {upload ? (
          <div className="media-upload" role="group" aria-label="Upload in progress">
            <span className="media-upload__label" aria-hidden="true">
              {percent === null ? 'Uploading…' : `${percent}%`}
            </span>
            <progress
              className="media-upload__bar"
              aria-label="Upload progress"
              max={100}
              /* No value is how a progress bar says "working, extent unknown". */
              {...(percent === null ? {} : { value: percent })}
            />
            <button type="button" className="media-upload__cancel" onClick={onCancelUpload}>
              Cancel
            </button>
          </div>
        ) : (
          remaining > 0 && (
            <button
              type="button"
              className={`media-dropzone${dragOver ? ' media-dropzone--over' : ''}`}
              aria-label="Add an image or video"
              onClick={() => inputRef.current?.click()}
            >
              <span aria-hidden="true">
                <IconImage size={18} />
                <br />
                Image or video
              </span>
            </button>
          )
        )}

        <input
          ref={inputRef}
          type="file"
          accept={STEP_MEDIA_ACCEPT}
          multiple
          hidden
          onChange={(event) => {
            acceptFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      {problems.length > 0 && (
        <div className="alert alert--error media-problems" role="alert">
          <ul>
            {problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
          <button
            type="button"
            className="button button--ghost button--icon"
            aria-label="Dismiss"
            onClick={onDismissProblems}
          >
            <IconClose size={14} />
          </button>
        </div>
      )}

      {open?.kind === 'image' && (
        <AnnotationEditor
          media={open}
          bullets={bullets}
          onChange={onUpdate}
          onClose={() => setDetailsFor(null)}
        />
      )}
      {open?.kind === 'video' && (
        <VideoDetailsDialog media={open} onChange={onUpdate} onClose={() => setDetailsFor(null)} />
      )}
    </>
  )
}

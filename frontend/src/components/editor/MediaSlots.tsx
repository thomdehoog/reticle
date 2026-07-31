import { useRef, useState, type DragEvent } from 'react'

import { MAX_MEDIA_PER_STEP, type Media } from '../../domain/types'
import { AnnotatedImage } from '../AnnotationOverlay'
import { IconClose, IconImage, IconPalette } from '../icons'
import { AnnotationEditor } from './AnnotationEditor'

interface MediaSlotsProps {
  media: Media[]
  uploading: boolean
  onAdd: (files: File[]) => void
  onRemove: (mediaId: string) => void
  onUpdate: (media: Media) => void
}

/**
 * The three image slots for a step.
 *
 * Accepts a drop anywhere on the strip as well as a click, because dragging a
 * screenshot straight from the desktop is how people actually add images, and
 * the file picker is the fallback rather than the main path.
 */
export function MediaSlots({ media, uploading, onAdd, onRemove, onUpdate }: MediaSlotsProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [annotating, setAnnotating] = useState<string | null>(null)

  const remaining = MAX_MEDIA_PER_STEP - media.length
  const annotatingMedia = media.find((image) => image.id === annotating) ?? null

  function acceptFiles(files: FileList | null) {
    if (!files) return
    const images = Array.from(files)
      .filter((file) => file.type.startsWith('image/'))
      .slice(0, remaining)
    if (images.length > 0) onAdd(images)
  }

  function onDrop(event: DragEvent) {
    event.preventDefault()
    setDragOver(false)
    acceptFiles(event.dataTransfer.files)
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
        {media.map((image) => (
          <div className="media-slot" key={image.id}>
            <AnnotatedImage src={image.url} alt={image.alt} annotations={image.annotations} />
            <button
              type="button"
              className="media-slot__action media-slot__annotate"
              aria-label="Annotate image"
              title="Draw on this image"
              onClick={() => setAnnotating(image.id)}
            >
              <IconPalette size={12} />
            </button>
            <button
              type="button"
              className="media-slot__action media-slot__remove"
              aria-label="Remove image"
              onClick={() => onRemove(image.id)}
            >
              <IconClose size={12} />
            </button>
            {image.annotations.length > 0 && (
              <span className="media-slot__badge">{image.annotations.length}</span>
            )}
          </div>
        ))}

        {remaining > 0 && (
          <button
            type="button"
            className={`media-dropzone${dragOver ? ' media-dropzone--over' : ''}`}
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? (
              'Uploading…'
            ) : (
              <span>
                <IconImage size={18} />
                <br />
                Drop or click
              </span>
            )}
          </button>
        )}

        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          multiple
          hidden
          onChange={(event) => {
            acceptFiles(event.target.files)
            event.target.value = ''
          }}
        />
      </div>

      {annotatingMedia && (
        <AnnotationEditor
          media={annotatingMedia}
          onChange={onUpdate}
          onClose={() => setAnnotating(null)}
        />
      )}
    </>
  )
}

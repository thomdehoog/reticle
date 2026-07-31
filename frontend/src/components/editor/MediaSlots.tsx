import { useRef, useState, type DragEvent } from 'react'

import { MAX_MEDIA_PER_STEP, type Media } from '../../domain/types'
import { IconClose, IconImage } from '../icons'

interface MediaSlotsProps {
  media: Media[]
  uploading: boolean
  onAdd: (files: File[]) => void
  onRemove: (mediaId: string) => void
}

/**
 * The three image slots for a step.
 *
 * Accepts a drop anywhere on the strip as well as a click, because dragging a
 * screenshot straight from the desktop is how people actually add images, and
 * the file picker is the fallback rather than the main path.
 */
export function MediaSlots({ media, uploading, onAdd, onRemove }: MediaSlotsProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const remaining = MAX_MEDIA_PER_STEP - media.length

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
          <img src={image.url} alt={image.alt} />
          <button
            type="button"
            className="media-slot__remove"
            aria-label="Remove image"
            onClick={() => onRemove(image.id)}
          >
            <IconClose size={12} />
          </button>
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
  )
}

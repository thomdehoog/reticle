/**
 * Adding and arranging the pictures for one step.
 *
 * A step can hold up to four pictures and one short video. This is where an
 * author drops files in, reorders them, removes one, or opens the drawing tools
 * to mark up a picture.
 *
 * The first picture is the large one a reader sees; the others appear as small
 * thumbnails they can click to swap in. So the order is not cosmetic, and this is
 * where it is decided.
 */

import { useRef, useState, type DragEvent } from 'react'

import { MAX_MEDIA_PER_STEP, type BulletColor, type Media } from '../../domain/types'
import { AnnotatedImage } from '../AnnotationOverlay'
import { formatClipLength } from '../StepGallery'
import { IconClose, IconImage, IconPalette } from '../icons'
import { AnnotationEditor } from './AnnotationEditor'

interface MediaSlotsProps {
  media: Media[]
  video: Media | null
  /** Which number each shape colour carries across the whole step. */
  shapeNumbers: Partial<Record<BulletColor, number>>
  uploading: boolean
  onAdd: (files: File[]) => void
  onRemove: (mediaId: string) => void
  onRemoveVideo: () => void
  onUpdate: (media: Media) => void
}

const ACCEPTED_TYPES = 'image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm'

/**
 * The media slots for a step.
 *
 * Accepts a drop anywhere on the strip as well as a click, because dragging a
 * screenshot straight from the desktop is how people actually add images, and
 * the file picker is the fallback rather than the main path.
 *
 * Each image carries its own alt field, beside the picture rather than behind a
 * second dialog: an unlabelled screenshot is announced as nothing at all, so a
 * screen-reader user working through a procedure hears the bullets and is told
 * there is a graphic where the annotated screenshot should be. The text saves
 * with the document like any other edit, so there is no separate "save the alt
 * text" step to forget.
 */
export function MediaSlots({
  media,
  video,
  shapeNumbers,
  uploading,
  onAdd,
  onRemove,
  onRemoveVideo,
  onUpdate,
}: MediaSlotsProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [annotating, setAnnotating] = useState<string | null>(null)

  const remaining = MAX_MEDIA_PER_STEP - media.length
  const annotatingMedia = media.find((image) => image.id === annotating) ?? null

  function acceptFiles(files: FileList | null) {
    if (!files) return
    const images = Array.from(files).filter((file) => file.type.startsWith('image/')).slice(0, remaining)
    /* One clip per step, so only the first is taken however many were dropped. */
    const clips = Array.from(files).filter((file) => file.type.startsWith('video/')).slice(0, 1)
    const accepted = [...images, ...clips]
    if (accepted.length > 0) onAdd(accepted)
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
        {media.map((image, index) => (
          <div className="media-slot" key={image.id}>
            {/* The buttons and the badge are positioned against the picture, so
                the picture is what they are inside. Measured from the slot they
                land on the description field below it instead, and the shape
                count sits on top of the author's own words. */}
            <div className="media-slot__frame">
              <AnnotatedImage
                src={image.url}
                alt={image.alt}
                annotations={image.annotations}
                shapeNumbers={shapeNumbers}
              />
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
            <input
              className="input media-slot__alt"
              value={image.alt}
              aria-label={`Description of image ${index + 1}`}
              placeholder="Describe this image"
              onChange={(event) => onUpdate({ ...image, alt: event.target.value })}
            />
          </div>
        ))}

        {video && (
          <div className="media-slot media-slot--video">
            <div className="media-slot__frame">
              <video src={video.url} poster={video.posterUrl ?? undefined} preload="metadata" muted />
              <button
                type="button"
                className="media-slot__action media-slot__remove"
                aria-label="Remove video"
                onClick={onRemoveVideo}
              >
                <IconClose size={12} />
              </button>
              <span className="media-slot__badge">
                {video.durationSeconds === null ? 'Video' : formatClipLength(video.durationSeconds)}
              </span>
            </div>
            <input
              className="input media-slot__alt"
              value={video.alt}
              aria-label="Description of the video"
              placeholder="Describe this video"
              onChange={(event) => onUpdate({ ...video, alt: event.target.value })}
            />
          </div>
        )}

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
          accept={ACCEPTED_TYPES}
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

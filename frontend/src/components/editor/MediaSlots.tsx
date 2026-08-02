/**
 * Adding and arranging the pictures for one step.
 *
 * A step can hold up to four pictures and one short video. This is where an
 * author drops files in, reorders them, removes one, or opens the drawing tools
 * to mark up a picture.
 *
 * It lays them out the way the step will actually be read: whichever item comes
 * first is shown large, and the rest sit beside it as small thumbnails. That is
 * not decoration — it is the point of the screen. The order decides which
 * picture a reader sees at full size, and an author choosing that order from a
 * row of four identical 110px squares was choosing blind, then opening the
 * published guide to find out what they had chosen. Now the large one is large
 * while it is being picked.
 *
 * The stage and the strip are returned as siblings rather than wrapped
 * together, exactly as `StepGallery` returns them, because the grid that places
 * them lives one level up and is shared between the two. Stacked anywhere else
 * they fall back to picture-then-strip, which is the phone's reading order.
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
  /** Make one picture the first, which is the one a reader sees large. */
  onPromote: (mediaId: string) => void
  onRemoveVideo: () => void
  onUpdate: (media: Media) => void
}

const ACCEPTED_TYPES = 'image/png,image/jpeg,image/webp,image/gif,video/mp4,video/webm'

/**
 * The media slots for a step.
 *
 * Accepts a drop anywhere on the stage or the strip as well as a click, because
 * dragging a screenshot straight from the desktop is how people actually add
 * images, and the file picker is the fallback rather than the main path.
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
  onPromote,
  onRemoveVideo,
  onUpdate,
}: MediaSlotsProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [annotating, setAnnotating] = useState<string | null>(null)

  const remaining = MAX_MEDIA_PER_STEP - media.length
  const annotatingMedia = media.find((image) => image.id === annotating) ?? null

  /* The clip leads if there is one, because that is what the reader shows
     large: a step that has a video exists because watching the movement is the
     instruction, and the stills are what it is broken down into. */
  const leadIsVideo = video !== null
  const thumbnails = leadIsVideo ? media : media.slice(1)

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

  const dropping = {
    onDragOver: (event: DragEvent) => {
      event.preventDefault()
      setDragOver(true)
    },
    onDragLeave: () => setDragOver(false),
    onDrop,
  }

  /**
   * The large picture, with the tools that act on it.
   *
   * Every tool lives here and nowhere else. They used to sit on all four
   * pictures at once, which put four 28px targets on a 65px thumbnail — they
   * overlapped each other and the picture underneath was invisible. Editing
   * one picture at a time is also how the step is read: one is large, the rest
   * are the strip you swap from.
   */
  function stageSlot(image: Media, index: number) {
    return (
      <div className="media-slot media-slot--stage" key={image.id}>
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
            intrinsicWidth={image.width}
            intrinsicHeight={image.height}
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
    )
  }

  /**
   * One of the small pictures: a single button that makes it the large one.
   *
   * A click here is the same gesture a reader makes on the published guide,
   * and it means the same thing — show me that one. The difference is that in
   * the editor it sticks, because which picture leads is exactly the decision
   * this screen exists to record. It is also all the reordering anyone needs:
   * promoting pictures one at a time reaches any arrangement, which two
   * arrow buttons per thumbnail did at four times the clutter.
   */
  function thumbSlot(image: Media, index: number) {
    const description = image.alt.trim()
    return (
      <button
        type="button"
        key={image.id}
        className="media-slot media-slot--thumb"
        aria-label={
          description
            ? `Make image ${index + 1} the main picture: ${description}`
            : `Make image ${index + 1} the main picture`
        }
        title="Make this the main picture"
        onClick={() => onPromote(image.id)}
      >
        <img src={image.url} alt="" loading="lazy" />
        {image.annotations.length > 0 && (
          <span className="media-slot__badge">{image.annotations.length}</span>
        )}
      </button>
    )
  }

  function videoSlot() {
    if (!video) return null
    return (
      <div className="media-slot media-slot--stage media-slot--video">
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
    )
  }

  /**
   * An empty slot, waiting for a picture. It is the same box the picture will
   * occupy, in the same place, so the step has one shape whether it has four
   * pictures or none and the card does not jump as they are added.
   *
   * `label` names the position rather than saying "drop or click" four times,
   * because a screen reader hears these one after another and "add the main
   * picture" is the difference between them.
   */
  function emptySlot(variant: 'stage' | 'thumb', label: string, key?: string) {
    return (
      <button
        type="button"
        key={key}
        className={`media-empty media-empty--${variant}${dragOver ? ' media-empty--over' : ''}`}
        aria-label={label}
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
      >
        {uploading ? (
          'Uploading…'
        ) : (
          <span>
            <IconImage size={variant === 'stage' ? 26 : 18} />
            <br />
            {variant === 'stage' ? 'Add the main picture' : 'Add'}
          </span>
        )}
      </button>
    )
  }

  const stage = leadIsVideo
    ? videoSlot()
    : media[0]
      ? stageSlot(media[0], 0)
      : emptySlot('stage', 'Add the main picture')

  /* Always three beside the large one, so the strip spans the column and lines
     up with the points underneath however many pictures the step has so far. A
     clip on the stage does not take an image slot, so a step with one holds
     four stills rather than three. */
  const thumbSlots = leadIsVideo
    ? remaining
    : Math.max(0, MAX_MEDIA_PER_STEP - 1 - thumbnails.length)

  return (
    <>
      <div className="media-stage" {...dropping}>
        {stage}
      </div>

      <div className="media-strip" {...dropping}>
        {thumbnails.map((image) => thumbSlot(image, media.indexOf(image)))}
        {Array.from({ length: thumbSlots }, (_, index) =>
          emptySlot('thumb', `Add a picture`, `empty-${index}`),
        )}
      </div>

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

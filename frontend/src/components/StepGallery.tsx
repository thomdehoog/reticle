/**
 * A step's pictures, the way a step is actually read.
 *
 * One large image carries the annotations and the attention; the step's other
 * images sit beneath it as thumbnails you swap in. The alternative — every
 * image at equal size in a row — was measured against ZMB's corpus and fails
 * the common case: a four-image step rendered each picture at roughly 160px
 * wide, which is smaller than the dialog box the red rectangle is pointing at.
 *
 * The shapes on the large image and the bullets beside it are drawn from the
 * same palette (`domain/palette.ts`), because "the red circle" is the sentence
 * the bullet is relying on.
 */

import { useRef, useState, type KeyboardEvent } from 'react'

import { numberShapeColors } from '../domain/guide'
import type { Media, Step } from '../domain/types'
import { AnnotatedImage } from './AnnotationOverlay'
import { IconPlay } from './icons'

/** "1:04" — how long a clip is, in the form a play control would show it. */
export function formatClipLength(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds))
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`
}

function VideoStage({ video }: { video: Media }) {
  return (
    <>
      {/* preload="metadata": the clip is beside the text of a step somebody is
          working through, so it must not spend the bench's bandwidth until it
          is asked for, but it must know its own length and first frame. */}
      <video
        className="step__video"
        src={video.url}
        poster={video.posterUrl ?? undefined}
        controls
        preload="metadata"
        aria-label={video.alt || 'Video for this step'}
      />
      {/* Paper cannot play it, and a blank rectangle on a printed procedure
          reads as a missing figure rather than as a clip. */}
      <p className="print-only step__video-note">
        Video{video.alt ? `: ${video.alt}` : ''}
        {video.durationSeconds !== null && ` (${formatClipLength(video.durationSeconds)})`} — open
        this step in Reticle to watch it.
      </p>
    </>
  )
}

function Thumb({
  item,
  index,
  selected,
  buttonRef,
  onSelect,
  onKeyDown,
}: {
  item: Media
  index: number
  selected: boolean
  buttonRef: (element: HTMLButtonElement | null) => void
  onSelect: () => void
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void
}) {
  const label =
    item.kind === 'video'
      ? item.alt
        ? `Show the video: ${item.alt}`
        : 'Show the video'
      : item.alt
        ? `Show image ${index}: ${item.alt}`
        : `Show image ${index}`

  return (
    <button
      type="button"
      ref={buttonRef}
      className={`step__thumb${selected ? ' step__thumb--current' : ''}`}
      aria-pressed={selected}
      aria-label={label}
      onClick={onSelect}
      onKeyDown={onKeyDown}
    >
      {item.kind === 'video' ? (
        <span className="step__thumb-video">
          {item.posterUrl ? <img src={item.posterUrl} alt="" /> : <span className="step__thumb-blank" />}
          <span className="step__thumb-play">
            <IconPlay size={14} />
            {item.durationSeconds !== null && (
              <span className="step__thumb-length">{formatClipLength(item.durationSeconds)}</span>
            )}
          </span>
        </span>
      ) : (
        <img src={item.url} alt="" loading="lazy" />
      )}
    </button>
  )
}

/**
 * A step's media, with the selected item large and the rest as thumbnails.
 *
 * A step with a single image gets no thumbnail strip: a row of one is a control
 * that does nothing, and it costs the picture height on a phone.
 */
export function StepGallery({ step }: { step: Step }) {
  /* The clip leads: a step that has one exists because watching the movement is
     the instruction, and the stills are what it is broken down into. */
  const items = step.video ? [step.video, ...step.media] : step.media

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const buttons = useRef<(HTMLButtonElement | null)[]>([])

  if (items.length === 0) return null

  const selected = items.find((item) => item.id === selectedId) ?? items[0]

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
    event.preventDefault()
    const delta = event.key === 'ArrowRight' ? 1 : items.length - 1
    const next = (index + delta) % items.length
    setSelectedId(items[next].id)
    buttons.current[next]?.focus()
  }

  return (
    <div className="step__media">
      <div className="step__stage">
        {selected.kind === 'video' ? (
          <VideoStage video={selected} />
        ) : (
          <AnnotatedImage
            src={selected.url}
            alt={selected.alt}
            annotations={selected.annotations}
            /* Numbered across the whole step, not per picture: the bullets
               beside the strip do not change when a thumbnail is swapped in. */
            shapeNumbers={numberShapeColors(step)}
          />
        )}
      </div>

      {/* The strip is labelled "images", never "media": at a microscopy centre a
          medium is what cells grow in, and the word reads as the wrong noun. */}
      {items.length > 1 && (
        <div
          className="step__thumbs"
          role="group"
          aria-label={step.video ? 'Images and video for this step' : 'Images for this step'}
        >
          {items.map((item, index) => (
            <Thumb
              key={item.id}
              item={item}
              /* Numbered as a reader would count them, ignoring the clip. */
              index={step.video ? index : index + 1}
              selected={item.id === selected.id}
              buttonRef={(element) => {
                buttons.current[index] = element
              }}
              onSelect={() => setSelectedId(item.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

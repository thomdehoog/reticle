import { hasLargerOriginal } from '../domain/media'
import type { Media } from '../domain/types'
import { AnnotatedImage } from './AnnotationOverlay'

/**
 * A step's pictures and videos, as a reader sees them.
 *
 * A video gets the browser's own controls and loads only its metadata until
 * someone presses play: a guide can carry several, a phone at the microscope is
 * often on a weak connection, and nobody should pay for a clip they did not
 * ask to watch. `playsInline` keeps iOS from taking over the whole screen —
 * and with it the bullets the video is illustrating.
 */
function MediaItem({ item }: { item: Media }) {
  if (item.kind === 'video') {
    return (
      <div className="step__video">
        <video
          src={item.url}
          controls
          preload="metadata"
          playsInline
          aria-label={item.alt || 'Video for this step'}
        />
        {/* Paper cannot play it; saying so beats an unexplained black box. */}
        <p className="print-only step__video-note">
          Video{item.alt ? `: ${item.alt}` : ''} — watch it in Reticle.
        </p>
      </div>
    )
  }

  /* What is drawn is the display copy: sharp at any size a step shows it,
     and a fraction of the bytes of a stitched panel. Annotations are fractions
     of the picture, so they sit in the same place on either file. The
     original is one click away for the reader who wants every pixel. */
  return (
    <figure className="step__figure">
      <AnnotatedImage
        src={item.displayUrl ?? item.url}
        alt={item.alt}
        annotations={item.annotations}
        width={item.width}
        height={item.height}
      />
      {hasLargerOriginal(item) && (
        <figcaption className="step__full-size">
          <a href={item.url} target="_blank" rel="noreferrer noopener">
            Open full size
            <span className="visually-hidden">
              {item.alt ? `: ${item.alt}` : ' image'} (opens in a new tab)
            </span>
          </a>
        </figcaption>
      )}
    </figure>
  )
}

export function StepMedia({ media }: { media: Media[] }) {
  if (media.length === 0) return null

  return (
    <div className={`step__media step__media--${media.length}`}>
      {media.map((item) => (
        <MediaItem key={item.id} item={item} />
      ))}
    </div>
  )
}

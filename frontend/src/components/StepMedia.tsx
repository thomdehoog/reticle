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

  return (
    <AnnotatedImage
      src={item.url}
      alt={item.alt}
      annotations={item.annotations}
      width={item.width}
      height={item.height}
    />
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

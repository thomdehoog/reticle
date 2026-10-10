import type { Media } from '../../domain/types'
import { Modal } from '../ui'

interface VideoDetailsDialogProps {
  media: Media
  onChange: (media: Media) => void
  onClose: () => void
}

/**
 * A step video, played back for its author, with the one thing they can say
 * about it.
 *
 * There is nothing to draw: annotations are fractions of a still picture and a
 * video has no still to pin them to. The description is what a screen reader
 * announces for the player, and what a printed guide shows in the video's place.
 */
export function VideoDetailsDialog({ media, onChange, onClose }: VideoDetailsDialogProps) {
  return (
    <Modal title="Step video" onClose={onClose}>
      <div className="annotate">
        <video className="video-preview" src={media.url} controls preload="metadata" playsInline />

        <div className="field">
          <label className="field__label" htmlFor="video-description">
            Description
          </label>
          <input
            id="video-description"
            className="input"
            value={media.alt}
            maxLength={1000}
            placeholder="e.g. Sliding the stage insert into place"
            onChange={(event) => onChange({ ...media, alt: event.target.value })}
          />
          <span className="field__hint">
            What the video shows, in a few words. Read out by screen readers and printed in the
            video&rsquo;s place on paper.
          </span>
        </div>

        <div className="page-actions">
          <button type="button" className="button button--primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Modal>
  )
}

import { useState } from 'react'

import { guideListBlock } from '../../domain/markdownEdit'
import { Modal } from '../ui'
import { TagInput } from './TagInput'

interface GuideListDialogProps {
  onClose: () => void
  onInsert: (block: string) => void
}

/** Asks which tags a guide list should gather, and hands back the finished block. */
export function GuideListDialog({ onClose, onInsert }: GuideListDialogProps) {
  const [tags, setTags] = useState<string[]>([])
  const [heading, setHeading] = useState('')

  return (
    <Modal title="Insert a guide list" onClose={onClose}>
      <p className="field__hint" style={{ marginBottom: '1rem' }}>
        A guide list gathers every published guide carrying the tags you choose, and keeps itself up
        to date as guides are added.
      </p>

      <div className="field">
        <span className="field__label">Tags</span>
        <TagInput tags={tags} onChange={setTags} />
      </div>

      <div className="field">
        <label className="field__label" htmlFor="guidelist-heading">
          Heading (optional)
        </label>
        <input
          id="guidelist-heading"
          className="input"
          value={heading}
          placeholder="e.g. Confocal systems"
          onChange={(event) => setHeading(event.target.value)}
        />
      </div>

      <div className="page-actions">
        <button
          type="button"
          className="button button--primary"
          disabled={tags.length === 0}
          onClick={() => onInsert(guideListBlock(tags, heading))}
        >
          Insert
        </button>
        <button type="button" className="button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  )
}

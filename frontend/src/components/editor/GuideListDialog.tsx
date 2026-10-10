import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useApi } from '../../api/context'
import { guideQueries } from '../../queries/guides'

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

  /* The same request the finished block will make, asked now: the commonest
     mistake with a guide list is one tag too many — a guide must carry all of
     them — and an empty list is much easier to understand before inserting it. */
  const api = useApi()
  const matching = useQuery({
    ...guideQueries.list(api, { tags: tags.join(',') }),
    enabled: tags.length > 0,
  })
  const count = matching.data?.length

  return (
    <Modal title="Insert a guide list" onClose={onClose}>
      <p className="field__hint" style={{ marginBottom: '1rem' }}>
        A guide list gathers every published guide carrying the tags you choose, and keeps itself up
        to date as guides are added.
      </p>

      <div className="field">
        <span className="field__label">Tags</span>
        <TagInput tags={tags} onChange={setTags} />
        <span className="field__hint" role="status">
          {tags.length === 0 && 'Start typing to pick from the tags in use.'}
          {tags.length > 0 && count === undefined && !matching.isError && 'Looking for guides…'}
          {tags.length > 0 &&
            count !== undefined &&
            (count === 0
              ? `No guide carries ${tags.length === 1 ? 'this tag' : 'all of these tags'} yet — the list will be empty until one does.`
              : `${count} ${count === 1 ? 'guide carries' : 'guides carry'} ${tags.length === 1 ? 'this tag' : 'all of these tags'} right now.`)}
        </span>
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

/**
 * Tag editing for a guide.
 *
 * Tags are how a guide is found: it lives in one category but surfaces on every
 * wiki page that asks for one of its tags. Getting them on a guide has to be
 * effortless, so this suggests existing tags as you type rather than leaving
 * people to guess, which is what stops the same instrument acquiring four
 * spellings.
 */

import { useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { useApi } from '../../auth/AuthContext'
import { useAsync } from '../../hooks/useAsync'
import { IconClose } from '../icons'

/** Matches the server's slug rule, so what you see is what gets stored. */
export function slugifyTag(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

interface TagInputProps {
  tags: string[]
  onChange: (tags: string[]) => void
}

export function TagInput({ tags, onChange }: TagInputProps) {
  const api = useApi()
  const inputRef = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState('')

  const { data: known } = useAsync(() => api.listTags(), [api])

  const suggestions = useMemo(() => {
    const typed = slugifyTag(draft)
    if (typed === '') return []
    return (known ?? [])
      .filter((tag) => tag.slug.includes(typed) && !tags.includes(tag.slug))
      .slice(0, 6)
  }, [draft, known, tags])

  function add(value: string) {
    const slug = slugifyTag(value)
    if (slug === '' || tags.includes(slug)) {
      setDraft('')
      return
    }
    onChange([...tags, slug])
    setDraft('')
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      add(draft)
      return
    }
    if (event.key === 'Backspace' && draft === '' && tags.length > 0) {
      event.preventDefault()
      onChange(tags.slice(0, -1))
    }
  }

  return (
    <div className="tag-input">
      <div className="tag-input__chips">
        {tags.map((tag) => (
          <span className="tag" key={tag}>
            {tag}
            <button
              type="button"
              className="tag__remove"
              aria-label={`Remove tag ${tag}`}
              onClick={() => onChange(tags.filter((candidate) => candidate !== tag))}
            >
              <IconClose size={11} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          className="tag-input__field"
          value={draft}
          placeholder={tags.length === 0 ? 'e.g. stellaris, confocal' : 'Add a tag…'}
          aria-label="Add a tag"
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => add(draft)}
        />
      </div>

      {suggestions.length > 0 && (
        <ul className="tag-input__suggestions">
          {suggestions.map((tag) => (
            <li key={tag.id}>
              <button
                type="button"
                onMouseDown={(event) => {
                  event.preventDefault()
                  add(tag.slug)
                  inputRef.current?.focus()
                }}
              >
                <span>{tag.slug}</span>
                <span className="tag-input__count">{tag.guideCount}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

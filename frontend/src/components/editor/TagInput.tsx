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

/** The longest tag the server stores. */
export const MAX_TAG_LENGTH = 120

/** As many tags as one guide may carry, matching the server's ceiling. */
export const MAX_TAGS_PER_GUIDE = 40

/**
 * Transliterations that a fold to ASCII cannot make on its own.
 *
 * NFKD splits an umlaut into a letter and a combining accent, so dropping
 * non-ASCII afterwards leaves the letter. It does nothing for ß, æ or ø, which
 * are letters in their own right rather than accented ones.
 */
const TRANSLITERATIONS: Record<string, string> = {
  ß: 'ss',
  æ: 'ae',
  œ: 'oe',
  ø: 'o',
  đ: 'd',
  ł: 'l',
}

/**
 * Matches the server's slug rule, so what you see is what gets stored.
 *
 * The transliteration is the whole point at a Zurich facility. Deleting every
 * character outside `[a-z0-9]` turns "Präparation" into "pr-paration" and
 * "Messgröße" into "messgr-e" — unreadable, unguessable, and *different* from
 * what the same word becomes anywhere else in the system. One concept would
 * then have two tags and a guide would not appear where its author put it,
 * which is precisely the failure tags exist to prevent.
 */
export function slugifyTag(value: string): string {
  const translated = value
    .trim()
    .toLowerCase()
    .replace(/[ßæœøđł]/g, (character) => TRANSLITERATIONS[character] ?? character)

  return translated
    .normalize('NFKD')
    // Dropping every non-ASCII code point after decomposition is the point,
    // control characters included: a tag slug goes into a URL.
    // eslint-disable-next-line no-control-regex
    .replace(/[^\x00-\x7F]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, MAX_TAG_LENGTH)
    .replace(/-+$/, '')
}

interface TagInputProps {
  tags: string[]
  onChange: (tags: string[]) => void
}

export function TagInput({ tags, onChange }: TagInputProps) {
  const api = useApi()
  const inputRef = useRef<HTMLInputElement>(null)
  const [draft, setDraft] = useState('')
  const [refusal, setRefusal] = useState<string | null>(null)

  const { data: known } = useAsync(() => api.listTags(), [api])

  const suggestions = useMemo(() => {
    const typed = slugifyTag(draft)
    if (typed === '') return []
    return (known ?? [])
      .filter((tag) => tag.slug.includes(typed) && !tags.includes(tag.slug))
      .slice(0, 6)
  }, [draft, known, tags])

  function add(value: string) {
    if (value.trim() === '') {
      setDraft('')
      setRefusal(null)
      return
    }

    const slug = slugifyTag(value)

    /**
     * Silence is the wrong answer here. A tag written in a script that has no
     * ASCII form — 顕微鏡, or an emoji — slugifies to nothing, and clearing the
     * field made the author's typing vanish with no chip and no explanation.
     * The text stays put so it can be corrected, and says why.
     */
    if (slug === '') {
      setRefusal('A tag needs at least one Latin letter or digit.')
      return
    }

    if (tags.includes(slug)) {
      setDraft('')
      setRefusal(null)
      return
    }

    /* The server refuses a guide carrying more than this, and it refuses the
       whole document — so the 41st chip would not simply fail to stick, it
       would turn every autosave from then on into "could not save". */
    if (tags.length >= MAX_TAGS_PER_GUIDE) {
      setRefusal(`A guide can carry at most ${MAX_TAGS_PER_GUIDE} tags.`)
      return
    }

    onChange([...tags, slug])
    setDraft('')
    setRefusal(null)
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
          onChange={(event) => {
            setDraft(event.target.value)
            setRefusal(null)
          }}
          onKeyDown={onKeyDown}
          onBlur={() => add(draft)}
        />
      </div>

      {refusal && (
        <p className="field__error" role="alert">
          {refusal}
        </p>
      )}

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

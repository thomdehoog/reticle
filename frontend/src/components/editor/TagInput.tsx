/**
 * Tag editing for a guide.
 *
 * Tags are how a guide is found: it lives in one category but surfaces on every
 * wiki page that asks for one of its tags. Getting them on a guide has to be
 * effortless, so this suggests existing tags as you type rather than leaving
 * people to guess, which is what stops the same instrument acquiring four
 * spellings.
 */

import { useQuery } from '@tanstack/react-query'
import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { useApi } from '../../api/context'
import { slugifyTag } from '../../domain/slug'
import { MAX_TAG_LENGTH, MAX_TAGS_PER_GUIDE, type Tag } from '../../domain/types'
import { tagQueries } from '../../queries/tags'
import { IconClose } from '../icons'

/** Re-exported because the rule is this component's contract; it lives in the domain so it has no React around it. */
export { slugifyTag }

/** One stable empty list, so the suggestions are not recomputed on every render while tags load. */
const NO_TAGS: Tag[] = []

const MAX_SUGGESTIONS = 6

/** Too short to mean anything as a fragment: "a" is inside half the vocabulary. */
const MIN_CONTAINED_LENGTH = 3

/**
 * The existing tags worth offering for what has been typed.
 *
 * Matching runs both ways. The usual one — the tag contains what was typed —
 * completes a word in progress. The reverse — what was typed contains the tag —
 * is the one that protects the vocabulary: an author who has finished typing
 * "Stellaris-5" is shown that `stellaris` already exists, at the last moment
 * they can still choose it instead.
 */
export function suggestTags(known: Tag[], typed: string, taken: string[]): Tag[] {
  const slug = slugifyTag(typed)
  if (slug === '') return []

  const text = typed.trim().toLowerCase()
  const takenSlugs = new Set(taken.map(slugifyTag))

  const rank = (tag: Tag): number | null => {
    if (tag.slug === slug) return 0
    if (tag.slug.startsWith(slug) || tag.name.toLowerCase().startsWith(text)) return 1
    if (tag.slug.includes(slug) || tag.name.toLowerCase().includes(text)) return 2
    if (tag.slug.length >= MIN_CONTAINED_LENGTH && slug.includes(tag.slug)) return 3
    return null
  }

  return known
    .filter((tag) => !takenSlugs.has(tag.slug))
    .flatMap((tag) => {
      const score = rank(tag)
      return score === null ? [] : [{ tag, score }]
    })
    .sort((a, b) => a.score - b.score || b.tag.guideCount - a.tag.guideCount)
    .slice(0, MAX_SUGGESTIONS)
    .map((entry) => entry.tag)
}

interface TagInputProps {
  /**
   * The tags so far. Existing ones are slugs; one the author has just invented
   * may still be in the spelling it was typed in (see `spelling`).
   */
  tags: string[]
  onChange: (tags: string[]) => void
  /**
   * What a brand-new tag is stored as until the server has seen it.
   *
   * `as-typed` keeps the author's spelling — "LAS X" — because the server
   * takes the first spelling it sees of a new tag as that tag's display name,
   * and a slug sent in its place would name it "las-x" for ever. `slug` is for
   * places that need the identifier itself, like a guide-list block.
   */
  spelling?: 'slug' | 'as-typed'
}

export function TagInput({ tags, onChange, spelling = 'slug' }: TagInputProps) {
  const api = useApi()
  const inputRef = useRef<HTMLInputElement>(null)
  const listId = useId()
  const [draft, setDraft] = useState('')
  const [active, setActive] = useState(-1)
  const [dismissed, setDismissed] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)

  const { data: known = NO_TAGS } = useQuery(tagQueries.list(api))

  const suggestions = useMemo(() => suggestTags(known, draft, tags), [draft, known, tags])
  const draftSlug = slugifyTag(draft)
  const isNew = draftSlug !== '' && !known.some((tag) => tag.slug === draftSlug)
  const open = !dismissed && suggestions.length > 0

  function labelFor(tag: string): string {
    return known.find((candidate) => candidate.slug === slugifyTag(tag))?.name ?? tag
  }

  function isKnown(tag: string): boolean {
    return known.some((candidate) => candidate.slug === slugifyTag(tag))
  }

  function clear() {
    setDraft('')
    setActive(-1)
    setDismissed(false)
  }

  /**
   * Adds what was typed, or says why not. A refused tag stays in the box:
   * text that silently vanishes reads as a glitch, and leaves nothing to fix.
   */
  function add(value: string) {
    const typed = value.trim().replace(/\s+/g, ' ')
    if (typed === '') {
      clear()
      return
    }

    const slug = slugifyTag(typed)
    if (slug === '') {
      setRefusal('A tag needs at least one letter or digit (a–z, 0–9).')
      return
    }
    if (tags.some((tag) => slugifyTag(tag) === slug)) {
      clear()
      setRefusal(null)
      return
    }
    if (typed.length > MAX_TAG_LENGTH) {
      setRefusal(`A tag can be at most ${MAX_TAG_LENGTH} characters long.`)
      return
    }
    if (tags.length >= MAX_TAGS_PER_GUIDE) {
      setRefusal(`That is the limit: at most ${MAX_TAGS_PER_GUIDE} tags.`)
      return
    }

    const existing = known.some((tag) => tag.slug === slug)
    onChange([...tags, existing || spelling === 'slug' ? slug : typed])
    clear()
    setRefusal(null)
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' && suggestions.length > 0) {
      event.preventDefault()
      setDismissed(false)
      setActive((current) => (current + 1) % suggestions.length)
      return
    }
    if (event.key === 'ArrowUp' && open) {
      event.preventDefault()
      setActive((current) => (current <= 0 ? suggestions.length - 1 : current - 1))
      return
    }
    if (event.key === 'Escape' && open) {
      /* Closes the list and nothing else — inside a dialog, Escape would
         otherwise take the dialog with it. */
      event.preventDefault()
      setDismissed(true)
      setActive(-1)
      return
    }
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault()
      add(open && active >= 0 ? suggestions[active].slug : draft)
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
          <span
            className={`tag${isKnown(tag) ? '' : ' tag--new'}`}
            key={tag}
            title={isKnown(tag) ? undefined : 'A new tag — no other guide carries it yet'}
          >
            {labelFor(tag)}
            <button
              type="button"
              className="tag__remove"
              aria-label={`Remove tag ${labelFor(tag)}`}
              onClick={() => onChange(tags.filter((candidate) => candidate !== tag))}
            >
              <IconClose size={11} />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          className="tag-input__field"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          value={draft}
          placeholder={tags.length === 0 ? 'e.g. stellaris, confocal' : 'Add a tag…'}
          aria-label="Add a tag"
          onChange={(event) => {
            setDraft(event.target.value)
            setActive(-1)
            setDismissed(false)
            setRefusal(null)
          }}
          onKeyDown={onKeyDown}
          onBlur={() => add(draft)}
        />
      </div>

      {refusal && (
        <span className="field__error" role="alert">
          {refusal}
        </span>
      )}

      {/* Always in the document, so the combobox's `aria-controls` has a target. */}
      <ul className="tag-input__suggestions" id={listId} role="listbox" hidden={!open}>
        {open &&
          suggestions.map((tag, index) => (
            <li
              key={tag.id}
              id={`${listId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="tag-input__option"
              /* mousedown, and prevented: a click would arrive after the blur
                 that commits the half-typed text as a tag of its own. */
              onMouseDown={(event) => {
                event.preventDefault()
                add(tag.slug)
                inputRef.current?.focus()
              }}
              onMouseEnter={() => setActive(index)}
            >
              <span>
                {tag.name}
                {tag.name.toLowerCase() !== tag.slug && (
                  <span className="tag-input__slug"> {tag.slug}</span>
                )}
              </span>
              <span className="tag-input__count">
                {tag.guideCount} {tag.guideCount === 1 ? 'guide' : 'guides'}
              </span>
            </li>
          ))}
        {open && isNew && (
          <li className="tag-input__new" role="presentation">
            Enter adds “{draft.trim()}” as a new tag. Pick one above to reuse it instead.
          </li>
        )}
      </ul>
    </div>
  )
}

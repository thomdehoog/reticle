import {
  DIFFICULTY_LABELS,
  DIFFICULTY_ORDER,
  REVERSED_RANGE_MESSAGE,
  isReversedRange,
} from '../../domain/guide'
import {
  MAX_GUIDE_TITLE_LENGTH,
  type Category,
  type Difficulty,
  type Guide,
} from '../../domain/types'
import { AutoTextarea } from '../ui'
import { CategoryOptions } from './CategoryOptions'
import { TagInput } from './TagInput'

interface GuideDetailsPanelProps {
  guide: Guide
  categories: Category[]
  onChange: (mutator: (guide: Guide) => Guide) => void
}

/**
 * Reads a minutes box. Empty means "not estimated"; anything else is brought
 * to the whole, non-negative number the server insists on, so a stray "-" or a
 * decimal point cannot turn an autosave into a validation error.
 */
function parseMinutes(raw: string): number | null {
  if (raw.trim() === '') return null
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : null
}

/** Everything about a guide that is not a step: where it lives and how it is described. */
export function GuideDetailsPanel({ guide, categories, onChange }: GuideDetailsPanelProps) {
  return (
    <aside className="editor__sidebar">
      <div className="card">
        <div className="card__body">
          <div className="field">
            <label className="field__label" htmlFor="guide-title">
              Title
            </label>
            <input
              id="guide-title"
              className="input"
              maxLength={MAX_GUIDE_TITLE_LENGTH}
              value={guide.title}
              onChange={(event) => onChange((current) => ({ ...current, title: event.target.value }))}
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="guide-category">
              Category
            </label>
            <select
              id="guide-category"
              className="select"
              value={guide.categoryId}
              onChange={(event) =>
                onChange((current) => ({ ...current, categoryId: event.target.value }))
              }
            >
              <CategoryOptions categories={categories} />
            </select>
          </div>

          <div className="field">
            <span className="field__label">Tags</span>
            <TagInput
              tags={guide.tags}
              onChange={(tags) => onChange((current) => ({ ...current, tags }))}
            />
            <span className="field__hint">
              Tags decide where this guide appears. A wiki page can gather every guide carrying a
              tag, so one guide can show up under several instruments.
            </span>
          </div>

          <div className="field">
            <label className="field__label" htmlFor="guide-summary">
              Summary
            </label>
            <AutoTextarea
              id="guide-summary"
              className="textarea"
              rows={2}
              value={guide.summary}
              placeholder="One line shown in listings."
              onChange={(event) =>
                onChange((current) => ({ ...current, summary: event.target.value }))
              }
            />
          </div>

          <div className="field">
            <label className="field__label" htmlFor="guide-difficulty">
              Difficulty
            </label>
            <select
              id="guide-difficulty"
              className="select"
              value={guide.difficulty}
              onChange={(event) =>
                onChange((current) => ({ ...current, difficulty: event.target.value as Difficulty }))
              }
            >
              {DIFFICULTY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {DIFFICULTY_LABELS[value]}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <span className="field__label">Time required (minutes)</span>
            <div className="field-pair">
              <input
                className="input"
                type="number"
                min={0}
                aria-label="Time required, from"
                placeholder="from"
                value={guide.timeRequiredMinMinutes ?? ''}
                onChange={(event) =>
                  onChange((current) => ({
                    ...current,
                    timeRequiredMinMinutes: parseMinutes(event.target.value),
                  }))
                }
              />
              <span aria-hidden="true">–</span>
              <input
                className="input"
                type="number"
                min={0}
                aria-label="Time required, to"
                placeholder="to"
                value={guide.timeRequiredMaxMinutes ?? ''}
                onChange={(event) =>
                  onChange((current) => ({
                    ...current,
                    timeRequiredMaxMinutes: parseMinutes(event.target.value),
                  }))
                }
              />
            </div>
            {/* Said here as well as in the save error: while the range is
                backwards every autosave is refused, and "Could not save" alone
                does not tell the author which two boxes to look at. */}
            {isReversedRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes) && (
              <span className="field__error" role="alert">
                {REVERSED_RANGE_MESSAGE}
              </span>
            )}
            <span className="field__hint">
              A range is more honest than a single number. Leave the second box empty if it is
              reliably one duration.
            </span>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card__body">
          <div className="field">
            <label className="field__label" htmlFor="guide-intro">
              Introduction
            </label>
            <AutoTextarea
              id="guide-intro"
              className="textarea"
              rows={4}
              value={guide.introduction}
              placeholder="Context, scope, who this is for."
              onChange={(event) =>
                onChange((current) => ({ ...current, introduction: event.target.value }))
              }
            />
          </div>

          <div className="field" style={{ marginBottom: 0 }}>
            <label className="field__label" htmlFor="guide-conclusion">
              Conclusion
            </label>
            <AutoTextarea
              id="guide-conclusion"
              className="textarea"
              rows={3}
              value={guide.conclusion}
              placeholder="Shutdown, clean-up, what to do if it went wrong."
              onChange={(event) =>
                onChange((current) => ({ ...current, conclusion: event.target.value }))
              }
            />
          </div>
        </div>
      </div>
    </aside>
  )
}

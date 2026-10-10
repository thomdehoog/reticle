import { formatDate } from '../domain/dates'
import { DIFFICULTY_LABELS, formatDurationRange } from '../domain/guide'
import type { Guide, Step } from '../domain/types'
import { BulletList } from './BulletList'
import { StepMedia } from './StepMedia'
import { TagLink } from './TagLink'

function StepBlock({ step, number }: { step: Step; number: number }) {
  return (
    <section className="step">
      <span className="step__number" aria-hidden="true">
        {number}
      </span>
      <h2 className="step__title">
        <span className="visually-hidden">Step {number}: </span>
        {step.title || `Step ${number}`}
      </h2>
      <div className="step__body">
        <StepMedia media={step.media} />
        <BulletList bullets={step.bullets} />
      </div>
    </section>
  )
}

/**
 * Everything in a guide below its title: the facts strip, tags, introduction,
 * steps and conclusion.
 *
 * Its own component because two screens draw it — the reader, and the view of
 * a past version — and a snapshot that rendered even slightly differently from
 * the guide it was taken of would defeat the point of keeping one.
 */
export function GuideBody({ guide }: { guide: Guide }) {
  /**
   * Credit everyone who worked on it, without repeating the author. At a
   * facility the edit history is often the only surviving record of why a
   * procedure says what it says, and who to ask about it.
   */
  const otherContributors = guide.contributors.filter((person) => person.id !== guide.author.id)

  return (
    <>
      <dl className="guide__meta">
        <div className="guide__meta-item">
          <dt className="guide__meta-label">Difficulty</dt>
          <dd className="guide__meta-value">{DIFFICULTY_LABELS[guide.difficulty]}</dd>
        </div>
        <div className="guide__meta-item">
          <dt className="guide__meta-label">Time required</dt>
          <dd className="guide__meta-value">
            {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
          </dd>
        </div>
        <div className="guide__meta-item">
          <dt className="guide__meta-label">Steps</dt>
          <dd className="guide__meta-value">{guide.steps.length}</dd>
        </div>
        <div className="guide__meta-item">
          <dt className="guide__meta-label">Author</dt>
          <dd className="guide__meta-value">{guide.author.displayName}</dd>
        </div>
        {otherContributors.length > 0 && (
          <div className="guide__meta-item">
            <dt className="guide__meta-label">
              {otherContributors.length === 1 ? 'Contributor' : 'Contributors'}
            </dt>
            <dd className="guide__meta-value">
              {otherContributors.map((person) => person.displayName).join(', ')}
            </dd>
          </div>
        )}
        {guide.viewCount > 0 && (
          <div className="guide__meta-item">
            <dt className="guide__meta-label">Read</dt>
            <dd className="guide__meta-value">
              {guide.viewCount.toLocaleString()} {guide.viewCount === 1 ? 'time' : 'times'}
            </dd>
          </div>
        )}
        {guide.publishedAt && (
          <div className="guide__meta-item">
            <dt className="guide__meta-label">Version</dt>
            <dd className="guide__meta-value">
              {guide.version} · {formatDate(guide.publishedAt)}
            </dd>
          </div>
        )}
      </dl>

      {guide.tags.length > 0 && (
        <div className="tag-row">
          {guide.tags.map((tag) => (
            <TagLink key={tag} slug={tag} />
          ))}
        </div>
      )}

      {guide.introduction && <p className="guide__intro">{guide.introduction}</p>}

      {guide.steps.map((step, index) => (
        <StepBlock key={step.id} step={step} number={index + 1} />
      ))}

      {guide.conclusion && (
        <section className="step step--plain">
          <h2 className="step__title">Conclusion</h2>
          <p className="guide__conclusion">{guide.conclusion}</p>
        </section>
      )}
    </>
  )
}

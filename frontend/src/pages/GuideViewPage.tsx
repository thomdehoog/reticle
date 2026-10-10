import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, getRouteApi } from '@tanstack/react-router'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { AnnotatedImage } from '../components/AnnotationOverlay'
import { BulletList } from '../components/BulletList'
import { IconEdit, IconPrint } from '../components/icons'
import { StatusBadge } from '../components/ui'
import { DIFFICULTY_LABELS, formatDurationRange } from '../domain/guide'
import type { Step } from '../domain/types'
import { useRecordView } from '../hooks/useRecordView'
import { categoryQueries } from '../queries/categories'
import { guideQueries } from '../queries/guides'

const route = getRouteApi('/g/$slug')

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
        {step.media.length > 0 && (
          <div className={`step__media${step.media.length === 1 ? ' step__media--single' : ''}`}>
            {step.media.map((image) => (
              <AnnotatedImage
                key={image.id}
                src={image.url}
                alt={image.alt}
                annotations={image.annotations}
              />
            ))}
          </div>
        )}
        <BulletList bullets={step.bullets} />
      </div>
    </section>
  )
}

export function GuideViewPage() {
  const { slug } = route.useParams()
  const api = useApi()
  const { can } = useSession()
  const { data: guide } = useSuspenseQuery(guideQueries.detail(api, slug))
  const { data: categories } = useSuspenseQuery(categoryQueries.list(api))

  /* Reading is counted here and nowhere else, so opening a guide in the editor
     does not inflate its own figure. */
  useRecordView(guide.id, (id) => api.recordGuideView(id))

  const category = categories.find((candidate) => candidate.id === guide.categoryId)

  /**
   * Credit everyone who worked on it, without repeating the author. At a
   * facility the edit history is often the only surviving record of why a
   * procedure says what it says, and who to ask about it.
   */
  const otherContributors = guide.contributors.filter((person) => person.id !== guide.author.id)

  return (
    <article className="guide">
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {category && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to="/c/$slug" params={{ slug: category.slug }}>
              {category.name}
            </Link>
          </>
        )}
      </nav>

      {/* Only ever seen on paper: a printout with no provenance is how somebody
          ends up following a superseded procedure taped to an instrument. */}
      <div className="print-only">
        Reticle · ZMB, University of Zurich — {guide.title}
        {guide.publishedAt &&
          ` · version ${guide.version}, published ${new Date(guide.publishedAt).toLocaleDateString()}`}
        {` · printed ${new Date().toLocaleDateString()}`}
      </div>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{guide.title}</h1>
          {guide.summary && <p className="page-header__sub">{guide.summary}</p>}
        </div>
        <div className="page-actions">
          {guide.status !== 'published' && <StatusBadge status={guide.status} />}
          <button className="button" type="button" onClick={() => window.print()}>
            <IconPrint />
            Print
          </button>
          {can('author') && (
            <Link className="button" to="/g/$id/edit" params={{ id: guide.id }}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      <div className="guide__meta">
        <div className="guide__meta-item">
          <span className="guide__meta-label">Difficulty</span>
          <span className="guide__meta-value">{DIFFICULTY_LABELS[guide.difficulty]}</span>
        </div>
        <div className="guide__meta-item">
          <span className="guide__meta-label">Time required</span>
          <span className="guide__meta-value">
            {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
          </span>
        </div>
        <div className="guide__meta-item">
          <span className="guide__meta-label">Steps</span>
          <span className="guide__meta-value">{guide.steps.length}</span>
        </div>
        <div className="guide__meta-item">
          <span className="guide__meta-label">Author</span>
          <span className="guide__meta-value">{guide.author.displayName}</span>
        </div>
        {otherContributors.length > 0 && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">
              {otherContributors.length === 1 ? 'Contributor' : 'Contributors'}
            </span>
            <span className="guide__meta-value">
              {otherContributors.map((person) => person.displayName).join(', ')}
            </span>
          </div>
        )}
        {guide.viewCount > 0 && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">Read</span>
            <span className="guide__meta-value">
              {guide.viewCount.toLocaleString()} {guide.viewCount === 1 ? 'time' : 'times'}
            </span>
          </div>
        )}
        {guide.publishedAt && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">Version</span>
            <span className="guide__meta-value">
              {guide.version} · {new Date(guide.publishedAt).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>

      {guide.tags.length > 0 && (
        <div className="tag-row">
          {guide.tags.map((tag) => (
            <Link key={tag} className="tag" to="/t/$tag" params={{ tag }}>
              {tag}
            </Link>
          ))}
        </div>
      )}

      {guide.introduction && <p className="guide__intro">{guide.introduction}</p>}

      {guide.steps.map((step, index) => (
        <StepBlock key={step.id} step={step} number={index + 1} />
      ))}

      {guide.conclusion && (
        <section className="step" style={{ gridTemplateColumns: '1fr' }}>
          <div>
            <h2 className="step__title">Conclusion</h2>
            <p style={{ marginTop: '0.5rem' }}>{guide.conclusion}</p>
          </div>
        </section>
      )}
    </article>
  )
}

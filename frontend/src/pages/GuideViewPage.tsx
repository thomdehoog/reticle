import { Link, useParams } from 'react-router-dom'

import { useApi, useAuth } from '../auth/AuthContext'
import { BulletList } from '../components/BulletList'
import { IconEdit } from '../components/icons'
import { EmptyState, ErrorAlert, Spinner, StatusBadge } from '../components/ui'
import { DIFFICULTY_LABELS, formatDuration } from '../domain/guide'
import type { Step } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

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
              <img key={image.id} src={image.url} alt={image.alt} loading="lazy" />
            ))}
          </div>
        )}
        <BulletList bullets={step.bullets} />
      </div>
    </section>
  )
}

export function GuideViewPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const guide = await api.getGuide(slug)
      const [categories, allGuides] = await Promise.all([
        api.listCategories(),
        guide.prerequisiteIds.length > 0 ? api.listGuides() : Promise.resolve([]),
      ])
      return { guide, categories, allGuides }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That guide does not exist.</EmptyState>

  const { guide, categories, allGuides } = data
  const category = categories.find((candidate) => candidate.id === guide.categoryId)
  const prerequisites = allGuides.filter((candidate) =>
    guide.prerequisiteIds.includes(candidate.id),
  )

  return (
    <article className="guide">
      <nav className="breadcrumb">
        <Link to="/">Guides</Link>
        {category && (
          <>
            <span className="breadcrumb__sep">/</span>
            <Link to={`/c/${category.slug}`}>{category.name}</Link>
          </>
        )}
      </nav>

      <div className="page-header">
        <div className="page-header__text">
          <h1>{guide.title}</h1>
          {guide.summary && <p className="page-header__sub">{guide.summary}</p>}
        </div>
        <div className="page-actions">
          {guide.status !== 'published' && <StatusBadge status={guide.status} />}
          {can('author') && (
            <Link className="button" to={`/g/${guide.id}/edit`}>
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
          <span className="guide__meta-value">{formatDuration(guide.timeRequiredMinutes)}</span>
        </div>
        <div className="guide__meta-item">
          <span className="guide__meta-label">Steps</span>
          <span className="guide__meta-value">{guide.steps.length}</span>
        </div>
        <div className="guide__meta-item">
          <span className="guide__meta-label">Author</span>
          <span className="guide__meta-value">{guide.author.displayName}</span>
        </div>
        {guide.publishedAt && (
          <div className="guide__meta-item">
            <span className="guide__meta-label">Version</span>
            <span className="guide__meta-value">
              {guide.version} · {new Date(guide.publishedAt).toLocaleDateString()}
            </span>
          </div>
        )}
      </div>

      {prerequisites.length > 0 && (
        <div className="alert alert--info">
          <strong>Before you start:</strong>{' '}
          {prerequisites.map((prerequisite, index) => (
            <span key={prerequisite.id}>
              {index > 0 && ', '}
              <Link to={`/g/${prerequisite.slug}`}>{prerequisite.title}</Link>
            </span>
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

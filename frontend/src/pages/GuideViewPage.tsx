/**
 * A guide as a reader sees it.
 *
 * Step by step, big picture on the left with any shapes drawn over it, coloured
 * points on the right. This is the screen the whole product exists to produce,
 * and it is intentionally plain: somebody is reading it with one hand while doing
 * something with the other.
 *
 * What is above step 1 is held to what a reader acts on — the title, the one
 * line saying what this is, how hard it is and how long it takes. The name of
 * the author and the tags are at the bottom, because "who do I ask about this"
 * and "what should I read next" are questions that arise after the procedure,
 * not on the way into it.
 */

import { Link, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { BulletList } from '../components/BulletList'
import { Revision } from '../components/Revision'
import { RichText } from '../components/RichText'
import { SectionNav } from '../components/SectionNav'
import { StepGallery } from '../components/StepGallery'
import { IconEdit, IconPrint } from '../components/icons'
import {
  DifficultyMeter,
  EmptyState,
  ErrorAlert,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { formatDurationRange, numberedSteps } from '../domain/guide'
import type { Step } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

/**
 * One block: a numbered step, a piece of context, or the pinned block.
 *
 * `number` is null for the two that are not numbered. They are otherwise drawn
 * the same way, because they hold the same things — pictures, shapes over them,
 * coloured points — and a reader learning two layouts to read one guide is a
 * cost with nothing on the other side of it.
 */
function StepBlock({ step, number }: { step: Step; number: number | null }) {
  /* Text-only steps are common — a shutdown sequence is often four sentences —
     and giving them the two-column layout leaves the instructions squeezed into
     half the width beside nothing at all. */
  const hasMedia = step.media.length > 0 || step.video !== null
  const fallbackTitle = number === null ? '' : `Step ${number}`

  return (
    <section className={`step step--${step.kind}`}>
      {number !== null && (
        <span className="step__number" aria-hidden="true">
          {number}
        </span>
      )}
      <h2 className="step__title">
        {number !== null && <span className="visually-hidden">Step {number}: </span>}
        {step.title || fallbackTitle}
      </h2>
      <div className={`step__body${hasMedia ? '' : ' step__body--text-only'}`}>
        <StepGallery step={step} />
        <BulletList step={step} />
      </div>
    </section>
  )
}

export function GuideViewPage() {
  const { slug = '' } = useParams()
  const api = useApi()
  const { can, organisation } = useAuth()

  const { data, error, loading } = useAsync(
    async () => {
      const [guide, categories] = await Promise.all([api.getGuide(slug), api.listCategories()])
      /* The rest of the section, for the list beside the guide. Asked for after
         the guide rather than alongside it, because the category is not known
         until the guide arrives. */
      const [siblings, pages] = await Promise.all([
        api.listGuides({ categoryId: guide.categoryId }),
        api.listPages({ categoryId: guide.categoryId }),
      ])
      return { guide, categories, siblings, pages }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That guide does not exist.</EmptyState>

  const { guide, categories, siblings, pages } = data
  const category = categories.find((candidate) => candidate.id === guide.categoryId)

  /**
   * Credit everyone who worked on it, without repeating the author. At a
   * facility the edit history is often the only surviving record of why a
   * procedure says what it says, and who to ask about it.
   */
  const otherContributors = guide.contributors.filter((person) => person.id !== guide.author.id)

  /* Only real steps are counted, so an info block sitting between steps 2 and 3
     does not make the next one 4. Worked out once, before anything is drawn,
     rather than with a counter that advances as the list renders. */
  const numbers = numberedSteps(guide.steps)

  return (
    <div className="with-sidebar">
      <SectionNav
        section={category ? { name: category.name, slug: category.slug } : null}
        pages={pages}
        guides={siblings}
        currentId={guide.id}
      />

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

      {/* Only ever seen on paper: a printout with no provenance is how somebody
          ends up following a superseded procedure taped to an instrument. */}
      <div className="print-only">
        {organisation ? `${organisation.name} — ` : ''}{guide.title}
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
            <Link className="button" to={`/g/${guide.id}/edit`}>
              <IconEdit />
              Edit
            </Link>
          )}
        </div>
      </div>

      {/* Difficulty and duration carry no labels: both change whether somebody
          starts the procedure now or after lunch, and neither needs a caption.
          The version and date sit with them, quieter, because they answer a
          different question - is what I am reading still the current
          procedure - which is asked less often but has no other answer. */}
      <div className="guide__meta">
        <DifficultyMeter difficulty={guide.difficulty} />
        <span className="guide__time">
          {formatDurationRange(guide.timeRequiredMinMinutes, guide.timeRequiredMaxMinutes)}
        </span>
        <Revision
          version={guide.version}
          publishedAt={guide.publishedAt}
          updatedAt={guide.updatedAt}
        />
      </div>

      {guide.introduction && (
        <div className="guide__intro">
          <RichText text={guide.introduction} />
        </div>
      )}

      {guide.steps.map((step) => (
        <StepBlock key={step.id} step={step} number={numbers.get(step.id) ?? null} />
      ))}

      <footer className="guide__credits">
        <p className="guide__byline">
          Written by {guide.author.displayName}
          {otherContributors.length > 0 &&
            `, with ${otherContributors.map((person) => person.displayName).join(', ')}`}
        </p>

        {guide.tags.length > 0 && (
          <div className="tag-row">
            {guide.tags.map((tag) => (
              <Link key={tag} className="tag" to={`/t/${encodeURIComponent(tag)}`}>
                {tag}
              </Link>
            ))}
          </div>
        )}
      </footer>
      </article>
    </div>
  )
}

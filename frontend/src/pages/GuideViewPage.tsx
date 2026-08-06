/**
 * A guide as a reader sees it.
 *
 * Step by step, big picture on the left with any shapes drawn over it, coloured
 * points on the right. This is the screen the whole product exists to produce,
 * and it is intentionally plain: somebody is reading it with one hand while doing
 * something with the other.
 *
 * What is above step 1 is held to what a reader acts on: the title, the one
 * line saying what this is, and one row carrying the version, the date and who
 * wrote it. Those three answer the same question — whether to trust the page in
 * front of you — so they are read together. The byline was at the bottom on the
 * reasoning that "who do I ask about this" comes after the procedure; it comes
 * before it as well, and a reader deciding whether this is the current way to
 * start a confocal wants the name in the same glance as the date.
 *
 * The tags stay at the bottom. "What should I read next" really is a question
 * that arises after the procedure and not on the way into it.
 */

import { Link, useParams } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { BulletList } from '../components/BulletList'
import { Revision } from '../components/Revision'
import { RichText } from '../components/RichText'
import { StepGallery } from '../components/StepGallery'
import { IconEdit, IconPrint } from '../components/icons'
import {
  EmptyState,
  ErrorAlert,
  Spinner,
  StatusBadge,
} from '../components/ui'
import { numberedSteps } from '../domain/guide'
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

  /* The categories are only for the breadcrumb. What else is in this section is
     the rail's business — asking for it here as well would be the same listing
     fetched twice to be drawn twice. */
  const { data, error, loading } = useAsync(
    async () => {
      const [guide, categories] = await Promise.all([api.getGuide(slug), api.listCategories()])
      return { guide, categories }
    },
    [api, slug],
  )

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return <EmptyState>That guide does not exist.</EmptyState>

  const { guide, categories } = data
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

      {/* The title and nothing under it.

          A guide arrived with two bodies of prose above its first step — the
          summary here, and the introduction below the meta row — saying the
          same thing twice at two different sizes. The summary is written for
          the places a guide is *listed*: it is what a tile, a search result and
          a group carry, and it earns its keep there. On the guide itself it
          only pushed the one row a reader checks first — which version, how
          old, whose — a paragraph further down the page. So the guide keeps one
          area for prose, and it is the introduction, which is the one an author
          writes for somebody who has already arrived. */}
      <div className="page-header">
        <div className="page-header__text">
          <h1>{guide.title}</h1>
        </div>
      </div>

      {/* The version and the date, and deliberately nothing else.
          Difficulty and duration are not shown: ZMB's corpus grades almost
          everything the same way and the estimates were inherited rather than
          measured, so a meter and a range that never vary say nothing while
          taking the eye first. Both are still imported and still stored - this
          is a decision about what a reader is shown, and it reverses by putting
          the two back in this row. What is left answers the question a reader
          actually asks, which is whether this is still the current procedure. */}
      <div className="guide__meta">
        <Revision
          version={guide.version}
          publishedAt={guide.publishedAt}
          updatedAt={guide.updatedAt}
        />
        {/* Beside the version and the date rather than under the last step.
            It used to sit in the footer, on the reasoning that "who do I ask
            about this" is a question you have after reading. It is also the
            question you have *before* reading, and it is the same question the
            version and the date answer: whether to trust the page. The three
            belong in one row. Written once — the footer keeps the tags. */}
        <span className="guide__byline">
          Written by {guide.author.displayName}
          {otherContributors.length > 0 &&
            `, with ${otherContributors.map((person) => person.displayName).join(', ')}`}
        </span>
      </div>

      {guide.introduction && (
        <div className="guide__intro">
          <RichText text={guide.introduction} />
        </div>
      )}

      {guide.steps.map((step) => (
        <StepBlock key={step.id} step={step} number={numbers.get(step.id) ?? null} />
      ))}

      {/* Printing and editing are staff controls, and neither is what somebody
          standing at an instrument came for. They sit after the procedure, the
          way a category's "edit landing page" does, so nothing between the
          title and step 1 belongs to anybody but the reader. */}
      <div className="page-actions page-actions--footer">
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

      <footer className="guide__credits">
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
  )
}

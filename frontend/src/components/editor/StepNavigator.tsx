/**
 * The rail that lists a guide's steps while it is being edited.
 *
 * ZMB's guides run to 8.3 steps on average and the longest is 33, and the
 * editor is a single column of cards: reaching step 27 to fix a typo means
 * scrolling past 26 others, and there is nothing that shows the shape of the
 * guide while you are writing it. The rail answers both — an outline that can
 * be read at a glance, and a jump straight to a step.
 *
 * It is an addition, not a replacement. The metadata panel opposite it stays
 * visible: a guide's title, tags and difficulty belong next to its steps rather
 * than behind tabs, which is where this editor deliberately parts company with
 * the one it replaces.
 *
 * Steps can be dragged into a new order here, and can equally be nudged with a
 * button: HTML5 drag events never fire on a touch screen, and dragging is a
 * poor way to move step 27 to the top of a 33-step guide in any case.
 */

import { useEffect, useRef, useState, type RefObject } from 'react'

import { moveStep } from '../../domain/guide'
import type { Step } from '../../domain/types'
import { IconChevronDown, IconChevronUp } from '../icons'

const UNTITLED = 'Untitled step'

/**
 * The band of the viewport, as an IntersectionObserver root margin, in which a
 * step counts as the one being worked on: from just below the sticky header
 * down to two thirds of the way. Biasing it towards the top means the rail
 * follows the step at the top of the screen rather than whichever card happens
 * to be tallest.
 */
const ACTIVE_BAND = '-72px 0px -35% 0px'

/**
 * The rendered step cards, in document order.
 *
 * `StepEditor` owns that markup and the rail only needs the nodes themselves —
 * to scroll to them and to watch them — so they are found by the class the
 * editor already puts on them rather than by threading a ref through every step.
 */
function stepCards(container: HTMLElement | null): HTMLElement[] {
  return container ? Array.from(container.querySelectorAll<HTMLElement>('.editor-step')) : []
}

function countLabel(count: number): string {
  if (count === 0) return 'No steps yet'
  return count === 1 ? '1 step' : `${count} steps`
}

interface StepNavigatorProps {
  steps: Step[]
  /** The element holding the rendered step cards. */
  stepsContainer: RefObject<HTMLElement | null>
  /** Receives the reordered array; the rail never mutates the guide itself. */
  onReorder: (steps: Step[]) => void
}

export function StepNavigator({ steps, stepsContainer, onReorder }: StepNavigatorProps) {
  const railRef = useRef<HTMLElement>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  const ids = steps.map((step) => step.id)
  const order = ids.join('\n')

  /**
   * Marks the step the author is looking at.
   *
   * Keyed on the list of step ids rather than on the array, because typing in a
   * bullet replaces that array on every keystroke and would otherwise tear the
   * observer down and build it again; only adding, removing or reordering steps
   * changes which cards exist. `ids` is derived from the same key, so the
   * closure cannot disagree with it.
   *
   * Where IntersectionObserver is unavailable the rail simply stops
   * highlighting. Jumping and reordering are what an author cannot do without.
   */
  useEffect(() => {
    if (!('IntersectionObserver' in globalThis)) return

    const cards = stepCards(stepsContainer.current)
    const idFor = new Map<Element, string>()
    cards.forEach((card, index) => {
      const id = ids[index]
      if (id) idFor.set(card, id)
    })

    const inBand = new Set<Element>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) inBand.add(entry.target)
          else inBand.delete(entry.target)
        }
        const leading = cards.find((card) => inBand.has(card))
        if (leading) setActiveId(idFor.get(leading) ?? null)
      },
      { rootMargin: ACTIVE_BAND },
    )

    cards.forEach((card) => observer.observe(card))
    return () => observer.disconnect()
  }, [order, stepsContainer])

  /**
   * Keeps the highlighted entry where it can be seen. A 33-step guide is taller
   * than the rail, so the step being edited would otherwise be marked somewhere
   * off the end of it. The rail is scrolled directly rather than through
   * `scrollIntoView`, which would also drag the page away from the author.
   */
  useEffect(() => {
    const rail = railRef.current
    const entry = rail?.querySelector<HTMLElement>('[aria-current]')
    if (!rail || !entry) return

    const railBox = rail.getBoundingClientRect()
    const entryBox = entry.getBoundingClientRect()
    if (entryBox.top < railBox.top) rail.scrollTop -= railBox.top - entryBox.top
    else if (entryBox.bottom > railBox.bottom) rail.scrollTop += entryBox.bottom - railBox.bottom
  }, [activeId])

  /**
   * Jumps to a step. The card's `scroll-margin-top` keeps its head clear of the
   * sticky app header; a system preference for less motion turns the glide into
   * a jump, since a long guide is a long way to slide.
   */
  function show(index: number) {
    const card = stepCards(stepsContainer.current)[index]
    if (!card) return

    const still = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    card.scrollIntoView({ behavior: still ? 'auto' : 'smooth', block: 'start' })
  }

  function move(from: number, delta: number) {
    onReorder(moveStep(steps, from, from + delta))
  }

  function dragOnto(index: number) {
    if (dragIndex === null || dragIndex === index) return
    onReorder(moveStep(steps, dragIndex, index))
    setDragIndex(index)
  }

  return (
    <nav className="step-nav" aria-label="Guide steps" ref={railRef}>
      <p className="step-nav__head">{countLabel(steps.length)}</p>

      <ol className="step-nav__list">
        {steps.map((step, index) => {
          const number = index + 1
          const title = step.title.trim()
          const thumbnail = step.media[0]

          return (
            <li
              key={step.id}
              className={`step-nav__item${dragIndex === index ? ' step-nav__item--dragging' : ''}`}
              draggable
              onDragStart={() => setDragIndex(index)}
              onDragEnter={() => dragOnto(index)}
              onDragOver={(event) => event.preventDefault()}
              onDragEnd={() => setDragIndex(null)}
            >
              <button
                type="button"
                className="step-nav__link"
                aria-current={step.id === activeId ? 'step' : undefined}
                aria-label={`Step ${number}: ${title || UNTITLED}`}
                onClick={() => show(index)}
              >
                <span className="step-nav__number">{number}</span>
                {thumbnail && <img className="step-nav__thumb" src={thumbnail.url} alt="" />}
                <span className={`step-nav__title${title ? '' : ' step-nav__title--empty'}`}>
                  {title || UNTITLED}
                </span>
              </button>

              <div className="step-nav__move">
                <button
                  type="button"
                  className="step-nav__nudge"
                  aria-label={`Move step ${number} up`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  <IconChevronUp size={13} />
                </button>
                <button
                  type="button"
                  className="step-nav__nudge"
                  aria-label={`Move step ${number} down`}
                  disabled={index === steps.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <IconChevronDown size={13} />
                </button>
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

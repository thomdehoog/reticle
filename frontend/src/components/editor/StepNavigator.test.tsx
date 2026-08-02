import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useRef, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createStep } from '../../domain/guide'
import type { Media, Step } from '../../domain/types'
import { StepNavigator } from './StepNavigator'

/**
 * jsdom implements no layout and so has no IntersectionObserver, the same gap
 * `src/test/setup.ts` fills for ResizeObserver. This stub is local rather than
 * global because only the rail needs it, and it reports nothing on its own: a
 * test says which step is on screen, which is the whole of what the rail asks.
 */
class FakeIntersectionObserver implements IntersectionObserver {
  static latest: FakeIntersectionObserver | null = null

  readonly root = null
  readonly rootMargin: string
  readonly thresholds: ReadonlyArray<number> = [0]
  private readonly targets = new Set<Element>()

  constructor(
    private readonly callback: IntersectionObserverCallback,
    options?: IntersectionObserverInit,
  ) {
    this.rootMargin = options?.rootMargin ?? '0px'
    FakeIntersectionObserver.latest = this
  }

  observe(target: Element): void {
    this.targets.add(target)
  }

  unobserve(target: Element): void {
    this.targets.delete(target)
  }

  disconnect(): void {
    this.targets.clear()
  }

  takeRecords(): IntersectionObserverEntry[] {
    return []
  }

  /** Reports `onScreen` as the only observed element in view, as scrolling to it would. */
  show(onScreen: Element): void {
    const entries = [...this.targets].map(
      (target) => ({ target, isIntersecting: target === onScreen }) as IntersectionObserverEntry,
    )
    act(() => this.callback(entries, this))
  }
}

function observer(): FakeIntersectionObserver {
  const latest = FakeIntersectionObserver.latest
  if (!latest) throw new Error('The navigator never started observing the steps.')
  return latest
}

const IMAGE: Media = {
  id: 'm-key',
  url: '/api/media/m-key',
  kind: 'image',
  alt: 'The laser key',
  width: 800,
  height: 600,
  durationSeconds: null,
  posterUrl: null,
  annotations: [],
}

function guideSteps(): Step[] {
  return [
    createStep({ id: 's1', kind: 'step', orderIndex: 0, title: 'Switch on the lasers' }),
    createStep({ id: 's2', kind: 'step', orderIndex: 1, title: '', media: [IMAGE] }),
    createStep({ id: 's3', kind: 'step', orderIndex: 2, title: 'Shut down' }),
  ]
}

/**
 * Stands in for the guide editor: the rail beside a column of step cards
 * carrying the class `StepEditor` gives them. Holding the steps in state means
 * a reorder is asserted the way an author sees it — the list comes back in a
 * different order — rather than as a callback argument.
 */
function Editor({ initial }: { initial: Step[] }) {
  const [steps, setSteps] = useState(initial)
  const stepsContainer = useRef<HTMLDivElement>(null)

  return (
    <div className="editor editor--with-nav">
      <StepNavigator steps={steps} stepsContainer={stepsContainer} onReorder={setSteps} />
      <div ref={stepsContainer}>
        {steps.map((step, index) => (
          <div className="editor-step" key={step.id} data-testid={`card-${step.id}`}>
            Step {index + 1}
          </div>
        ))}
      </div>
    </div>
  )
}

function entries(): HTMLElement[] {
  return screen.getAllByRole('button', { name: /^Step \d/ })
}

function entryLabels(): (string | null)[] {
  return entries().map((entry) => entry.getAttribute('aria-label'))
}

beforeEach(() => {
  globalThis.IntersectionObserver = FakeIntersectionObserver
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  FakeIntersectionObserver.latest = null
  Reflect.deleteProperty(globalThis, 'IntersectionObserver')
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
})

describe('StepNavigator', () => {
  it('lists every step, and says which ones are still untitled', () => {
    render(<Editor initial={guideSteps()} />)

    expect(entryLabels()).toEqual([
      'Step 1: Switch on the lasers',
      'Step 2: Untitled step',
      'Step 3: Shut down',
    ])
    expect(screen.getByText('3 steps')).toBeInTheDocument()
  })

  it("shows a step's first image as its thumbnail", () => {
    render(<Editor initial={guideSteps()} />)

    const [withoutImage, withImage] = entries()
    expect(withImage.querySelector('img')).toHaveAttribute('src', '/api/media/m-key')
    expect(withoutImage.querySelector('img')).toBeNull()
  })

  it('scrolls a step into view when its entry is clicked', async () => {
    const user = userEvent.setup()
    render(<Editor initial={guideSteps()} />)

    const card = screen.getByTestId('card-s3')
    const scrolled = vi.fn()
    card.scrollIntoView = scrolled

    await user.click(entries()[2])

    expect(scrolled).toHaveBeenCalledWith(expect.objectContaining({ block: 'start' }))
  })

  it('marks the step that is on screen, and moves the mark as the author scrolls', () => {
    render(<Editor initial={guideSteps()} />)

    observer().show(screen.getByTestId('card-s2'))
    expect(entries()[1]).toHaveAttribute('aria-current', 'step')
    expect(entries()[0]).not.toHaveAttribute('aria-current')

    observer().show(screen.getByTestId('card-s3'))
    expect(entries()[2]).toHaveAttribute('aria-current', 'step')
    expect(entries()[1]).not.toHaveAttribute('aria-current')
  })

  it('reorders the guide when one entry is dragged onto another', () => {
    render(<Editor initial={guideSteps()} />)

    const [first, , third] = screen.getAllByRole('listitem')
    fireEvent.dragStart(third)
    fireEvent.dragEnter(first)
    fireEvent.dragEnd(third)

    expect(entryLabels()).toEqual([
      'Step 1: Shut down',
      'Step 2: Switch on the lasers',
      'Step 3: Untitled step',
    ])
    expect(screen.getAllByTestId(/^card-/).map((card) => card.dataset.testid)).toEqual([
      'card-s3',
      'card-s1',
      'card-s2',
    ])
  })

  it('reorders from the keyboard, where dragging is not an option', async () => {
    const user = userEvent.setup()
    render(<Editor initial={guideSteps()} />)

    screen.getByRole('button', { name: 'Move step 3 up' }).focus()
    await user.keyboard('{Enter}')

    expect(entryLabels()).toEqual([
      'Step 1: Switch on the lasers',
      'Step 2: Shut down',
      'Step 3: Untitled step',
    ])
  })

  it('offers no move that would fall off either end of the guide', () => {
    render(<Editor initial={guideSteps()} />)

    expect(screen.getByRole('button', { name: 'Move step 1 up' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move step 3 down' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Move step 1 down' })).toBeEnabled()
  })

  /**
   * The outline used to count array positions, so an Info or Pinned block —
   * which is not a step and shows "—" on its own card and no number at all to
   * a reader — was listed as "Step 1", and every real step after it was named
   * one higher than the step card beside it and one higher than the guide a
   * reader is holding. Three answers to "which step is this".
   */
  it('numbers blocks the way the step cards and the reader do', () => {
    render(
      <Editor
        initial={[
          createStep({ id: 'p1', kind: 'pinned', orderIndex: 0, title: 'Read this first' }),
          createStep({ id: 's1', kind: 'step', orderIndex: 1, title: 'Switch on the lasers' }),
          createStep({ id: 'i1', kind: 'info', orderIndex: 2, title: 'Why the order matters' }),
          createStep({ id: 's2', kind: 'step', orderIndex: 3, title: 'Shut down' }),
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Step 1: Switch on the lasers' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Step 2: Shut down' })).toBeInTheDocument()
    // The unnumbered blocks are listed, and are not called steps.
    expect(screen.getByRole('button', { name: 'Block 1: Read this first' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Block 3: Why the order matters' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Step 3/ })).toBeNull()
    expect(screen.queryByRole('button', { name: /^Step 4/ })).toBeNull()
  })

  it('shows a dash for a block that carries no number, as its card does', () => {
    render(
      <Editor
        initial={[
          createStep({ id: 'p1', kind: 'pinned', orderIndex: 0, title: 'Read this first' }),
          createStep({ id: 's1', kind: 'step', orderIndex: 1, title: 'Switch on the lasers' }),
        ]}
      />,
    )

    const numbers = document.querySelectorAll('.step-nav__number')
    expect([...numbers].map((n) => n.textContent)).toEqual(['—', '1'])
  })

  it('names the move controls after the block they move, not its position', () => {
    render(
      <Editor
        initial={[
          createStep({ id: 'p1', kind: 'pinned', orderIndex: 0, title: 'Read this first' }),
          createStep({ id: 's1', kind: 'step', orderIndex: 1, title: 'Switch on the lasers' }),
        ]}
      />,
    )

    expect(screen.getByRole('button', { name: 'Move block 1 down' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Move step 1 up' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Move step 1 down' })).toBeDisabled()
  })

  it('still lists and jumps where the browser has no IntersectionObserver', async () => {
    Reflect.deleteProperty(globalThis, 'IntersectionObserver')
    const user = userEvent.setup()
    render(<Editor initial={guideSteps()} />)

    const card = screen.getByTestId('card-s2')
    const scrolled = vi.fn()
    card.scrollIntoView = scrolled

    await user.click(entries()[1])

    expect(entryLabels()).toHaveLength(3)
    expect(scrolled).toHaveBeenCalled()
  })
})

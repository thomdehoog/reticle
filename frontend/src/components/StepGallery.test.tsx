import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { imageFixture, videoFixture } from '../test/fakeServer'
import type { Annotation, Media, Step } from '../domain/types'
import { StepGallery } from './StepGallery'

function step(overrides: Partial<Step> = {}): Step {
  return {
    id: 's1',
    kind: 'step',
    orderIndex: 0,
    title: 'Seat the filter cube',
    bullets: [],
    media: [],
    video: null,
    ...overrides,
  }
}

function annotation(overrides: Partial<Annotation> = {}): Annotation {
  return {
    id: 'a1',
    shape: 'rectangle',
    color: 'red',
    x: 0.1,
    y: 0.1,
    width: 0.3,
    height: 0.2,
    ...overrides,
  }
}

const realResizeObserver = globalThis.ResizeObserver

/**
 * The overlay draws nothing until it has measured itself, and the global stub
 * in `test/setup.ts` deliberately reports no size. Any test that asserts on
 * drawn shapes has to hand it one.
 */
function measureAs(width: number, height: number) {
  globalThis.ResizeObserver = class implements ResizeObserver {
    constructor(private readonly callback: ResizeObserverCallback) {}
    observe(): void {
      this.callback([{ contentRect: { width, height } } as ResizeObserverEntry], this)
    }
    unobserve(): void {}
    disconnect(): void {}
  }
}

afterEach(() => {
  globalThis.ResizeObserver = realResizeObserver
})

const three: Media[] = [
  imageFixture({ id: 'm1', url: '/api/media/m1', alt: 'The stage' }),
  imageFixture({ id: 'm2', url: '/api/media/m2', alt: 'The turret' }),
  imageFixture({ id: 'm3', url: '/api/media/m3', alt: 'The eyepiece' }),
]

describe('StepGallery', () => {
  it('shows nothing at all for a step with no media', () => {
    const { container } = render(<StepGallery step={step()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('offers no thumbnail strip for a single image', () => {
    render(<StepGallery step={step({ media: [three[0]] })} />)

    expect(screen.getByAltText('The stage')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Images for this step' })).not.toBeInTheDocument()
  })

  it('swaps the large image when a thumbnail is chosen', async () => {
    const user = userEvent.setup()
    render(<StepGallery step={step({ media: three })} />)

    expect(screen.getByAltText('The stage')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Show image 3: The eyepiece' }))

    expect(screen.getByAltText('The eyepiece')).toBeInTheDocument()
    expect(screen.queryByAltText('The stage')).not.toBeInTheDocument()
  })

  it('can be driven from the keyboard alone', async () => {
    const user = userEvent.setup()
    render(<StepGallery step={step({ media: three })} />)

    await user.tab()
    await user.keyboard('{Enter}')
    expect(screen.getByAltText('The stage')).toBeInTheDocument()

    /* Space activates a button as well, and somebody working one-handed at an
       instrument will use whichever key their thumb is already on. */
    await user.tab()
    await user.keyboard(' ')
    expect(screen.getByAltText('The turret')).toBeInTheDocument()

    await user.keyboard('{ArrowRight}')
    expect(screen.getByAltText('The eyepiece')).toBeInTheDocument()

    /* Wrapping keeps the strip navigable without hunting for the end of it. */
    await user.keyboard('{ArrowRight}')
    expect(screen.getByAltText('The stage')).toBeInTheDocument()
  })

  it('marks the selected thumbnail for a screen reader, not by styling alone', async () => {
    const user = userEvent.setup()
    render(<StepGallery step={step({ media: three })} />)

    const second = screen.getByRole('button', { name: 'Show image 2: The turret' })
    expect(second).toHaveAttribute('aria-pressed', 'false')

    await user.click(second)
    expect(second).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Show image 1: The stage' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('draws the annotations belonging to the image on show, and only those', async () => {
    measureAs(640, 480)
    const user = userEvent.setup()
    render(
      <StepGallery
        step={step({
          media: [
            imageFixture({ id: 'm1', alt: 'The stage', annotations: [annotation({ id: 'a-red' })] }),
            imageFixture({
              id: 'm2',
              alt: 'The turret',
              annotations: [
                annotation({ id: 'a-blue-1', color: 'blue' }),
                annotation({ id: 'a-blue-2', color: 'blue', shape: 'ellipse' }),
              ],
            }),
          ],
        })}
      />,
    )

    const shapes = () => document.querySelectorAll('.annotated__overlay > g')
    expect(shapes()).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Show image 2: The turret' }))
    expect(shapes()).toHaveLength(2)
  })

  it('gives the video the large slot and a marked thumbnail beside the stills', () => {
    render(
      <StepGallery
        step={step({ media: [three[0]], video: videoFixture({ alt: 'Seating the cube' }) })}
      />,
    )

    const video = document.querySelector('video')
    expect(video).not.toBeNull()
    expect(video).toHaveAttribute('preload', 'metadata')
    expect(video).toHaveAttribute('poster', '/api/media/v1-poster')
    expect(video).toHaveAttribute('controls')

    expect(
      screen.getByRole('button', { name: 'Show the video: Seating the cube' }),
    ).toHaveAttribute('aria-pressed', 'true')
    /* The stills are still numbered from one — the clip is not "image 1". */
    expect(screen.getByRole('button', { name: 'Show image 1: The stage' })).toBeInTheDocument()
  })

  it('says on paper that a step has a clip, because paper cannot play it', () => {
    render(<StepGallery step={step({ video: videoFixture({ alt: 'Seating the cube' }) })} />)

    expect(screen.getByText(/Video: Seating the cube \(0:14\)/)).toBeInTheDocument()
  })

  it('swaps back from the video to a still', async () => {
    const user = userEvent.setup()
    render(<StepGallery step={step({ media: [three[0]], video: videoFixture() })} />)

    await user.click(screen.getByRole('button', { name: 'Show image 1: The stage' }))

    expect(screen.getByAltText('The stage')).toBeInTheDocument()
    expect(document.querySelector('video')).toBeNull()
  })
})

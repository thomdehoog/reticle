import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Media } from '../../domain/types'
import { MediaSlots } from './MediaSlots'

/**
 * The step's pictures, arranged the way the step will be read.
 *
 * These cover the arrangement rather than the styling: which picture is on the
 * stage, which are in the strip, and what a click on a small one does. The
 * argument for the whole screen is that the large picture in the editor is the
 * large picture in the guide, so it is worth a test that says so.
 */

function picture(id: string, overrides: Partial<Media> = {}): Media {
  return {
    id,
    url: `/api/media/${id}`,
    kind: 'image',
    alt: '',
    width: 800,
    height: 600,
    durationSeconds: null,
    posterUrl: null,
    annotations: [],
    ...overrides,
  }
}

function renderSlots(props: Partial<Parameters<typeof MediaSlots>[0]> = {}) {
  const onPromote = vi.fn()
  const onRemove = vi.fn()
  render(
    <MediaSlots
      media={[]}
      video={null}
      shapeNumbers={{}}
      uploading={false}
      onAdd={vi.fn()}
      onRemove={onRemove}
      onPromote={onPromote}
      onRemoveVideo={vi.fn()}
      onUpdate={vi.fn()}
      {...props}
    />,
  )
  return { onPromote, onRemove }
}

const stage = () => document.querySelector('.media-stage')
const strip = () => document.querySelector('.media-strip')

describe('MediaSlots', () => {
  it('puts the first picture on the stage and the rest in the strip', () => {
    renderSlots({ media: [picture('a'), picture('b'), picture('c')] })

    expect(stage()?.querySelectorAll('.media-slot--stage')).toHaveLength(1)
    expect(stage()?.querySelector('img')?.getAttribute('src')).toBe('/api/media/a')
    expect(strip()?.querySelectorAll('.media-slot--thumb')).toHaveLength(2)
  })

  /**
   * The four places are shown before anything is in them, so the screen
   * explains itself — a step is one large picture and up to three small ones —
   * and so the card does not jump about as they are added.
   */
  it('shows the four empty places on a step with no pictures', () => {
    renderSlots({ media: [] })

    expect(screen.getByRole('button', { name: 'Add the main picture' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Add a picture' })).toHaveLength(3)
  })

  it('keeps the strip three across as pictures fill it', () => {
    renderSlots({ media: [picture('a'), picture('b')] })

    expect(strip()?.querySelectorAll('.media-slot--thumb')).toHaveLength(1)
    expect(strip()?.querySelectorAll('.media-empty')).toHaveLength(2)
  })

  it('stops offering to add a picture once the step holds four', () => {
    renderSlots({ media: [picture('a'), picture('b'), picture('c'), picture('d')] })

    expect(strip()?.querySelectorAll('.media-slot--thumb')).toHaveLength(3)
    expect(screen.queryByRole('button', { name: /^Add/ })).toBeNull()
  })

  /* A clip does not take an image slot, so a step with one still holds four
     stills — and the strip shows all four places rather than three. */
  it('leaves room for four stills when a clip is on the stage', () => {
    renderSlots({ media: [picture('a')], video: picture('v', { kind: 'video' }) })

    expect(screen.getAllByRole('button', { name: 'Add a picture' })).toHaveLength(3)
  })

  /* The reader shows the clip large, because a step that has one exists so the
     movement can be watched. The editor has to agree, or the author is looking
     at a still that nobody will see first. */
  it('gives the stage to a clip, and puts every still in the strip', () => {
    renderSlots({ media: [picture('a')], video: picture('v', { kind: 'video' }) })

    expect(stage()?.querySelector('video')).not.toBeNull()
    expect(strip()?.querySelectorAll('.media-slot--thumb')).toHaveLength(1)
  })

  it('opens the file picker from an empty place', async () => {
    const user = userEvent.setup()
    renderSlots({ media: [] })
    const picker = document.querySelector('input[type=file]') as HTMLInputElement
    const clicked = vi.spyOn(picker, 'click')

    await user.click(screen.getByRole('button', { name: 'Add the main picture' }))
    expect(clicked).toHaveBeenCalled()

    await user.click(screen.getAllByRole('button', { name: 'Add a picture' })[0])
    expect(clicked).toHaveBeenCalledTimes(2)
  })

  it('makes a small picture the large one when it is clicked', async () => {
    const user = userEvent.setup()
    const { onPromote } = renderSlots({ media: [picture('a'), picture('b')] })

    await user.click(screen.getByRole('button', { name: 'Make image 2 the main picture' }))

    expect(onPromote).toHaveBeenCalledWith('b')
  })

  it('names a small picture by its description, so the choice is not blind', () => {
    renderSlots({ media: [picture('a'), picture('b', { alt: 'The filter turret' })] })

    expect(
      screen.getByRole('button', { name: 'Make image 2 the main picture: The filter turret' }),
    ).toBeInTheDocument()
  })

  /**
   * Every tool acts on the picture that is currently large. They used to sit on
   * all four at once, which put four 28px targets on a 65px thumbnail: they
   * overlapped each other and hid the picture they were supposed to be editing.
   */
  it('keeps the tools on the large picture and off the small ones', async () => {
    const user = userEvent.setup()
    const { onRemove } = renderSlots({ media: [picture('a'), picture('b')] })

    expect(screen.getAllByRole('button', { name: 'Remove image' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Annotate image' })).toHaveLength(1)
    expect(strip()?.querySelectorAll('button.media-slot__action')).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Remove image' }))
    expect(onRemove).toHaveBeenCalledWith('a')
  })

  it('describes only the picture being worked on', () => {
    renderSlots({ media: [picture('a'), picture('b')] })

    expect(screen.getAllByPlaceholderText('Describe this image')).toHaveLength(1)
  })

  it('counts the shapes drawn on a picture, wherever that picture is', () => {
    const marked = picture('b', {
      annotations: [
        { id: 'x', shape: 'rectangle', color: 'red', x: 0, y: 0, width: 0.2, height: 0.2 },
      ],
    })
    renderSlots({ media: [picture('a'), marked] })

    expect(strip()?.querySelector('.media-slot__badge')?.textContent).toBe('1')
  })
})

import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Annotation, Bullet, Media } from '../../domain/types'
import { AnnotationEditor } from './AnnotationEditor'

/*
 * Drawing itself is not exercised here: jsdom lays nothing out, so the drawing
 * surface has no size to draw on. The gesture's arithmetic is covered in
 * `domain/annotation.test.ts` and the gesture in the browser by `e2e/cms.mjs`.
 * What this covers is everything around it — which colour a shape will take,
 * and selecting and removing shapes without a pointer.
 */

const shape = (id: string, overrides: Partial<Annotation> = {}): Annotation => ({
  id,
  shape: 'rectangle',
  color: 'red',
  x: 0.1,
  y: 0.1,
  width: 0.2,
  height: 0.2,
  ...overrides,
})

const bullet = (id: string, text: string, color: Bullet['color']): Bullet => ({
  id,
  text,
  color,
  icon: null,
  level: 0,
})

const IMAGE: Media = {
  id: 'm1',
  kind: 'image',
  url: '/api/media/m1',
  displayUrl: '/api/media/m1?size=display',
  alt: '',
  width: 800,
  height: 600,
  annotations: [],
}

function Harness({
  initial = IMAGE,
  bullets = [],
  onChange,
}: {
  initial?: Media
  bullets?: Bullet[]
  onChange?: (media: Media) => void
}) {
  const [media, setMedia] = useState(initial)
  return (
    <AnnotationEditor
      media={media}
      bullets={bullets}
      onChange={(next) => {
        setMedia(next)
        onChange?.(next)
      }}
      onClose={() => undefined}
    />
  )
}

function pressedColour(): string | null {
  return within(screen.getByRole('group', { name: 'Colour' }))
    .getAllByRole('button')
    .find((button) => button.getAttribute('aria-pressed') === 'true')!
    .getAttribute('aria-label')
}

describe('AnnotationEditor', () => {
  it('opens on the colour of the step\'s first coloured bullet', () => {
    render(
      <Harness
        bullets={[
          bullet('b1', 'Open the software.', 'black'),
          bullet('b2', 'Click the green button.', 'green'),
          bullet('b3', 'Then the blue one.', 'blue'),
        ]}
      />,
    )

    expect(pressedColour()).toBe('Green')
  })

  it('opens on red when no bullet has a colour of its own', () => {
    render(<Harness bullets={[bullet('b1', 'Open the software.', 'black')]} />)

    expect(pressedColour()).toBe('Red')
  })

  it('takes a bullet\'s colour when that bullet is picked', async () => {
    const user = userEvent.setup()
    render(
      <Harness
        bullets={[
          bullet('b1', 'Click the green button.', 'green'),
          bullet('b2', 'Then the violet one.', 'violet'),
          bullet('b3', '   ', 'orange'),
        ]}
      />,
    )

    const bullets = screen.getByRole('group', { name: 'Match a bullet' })
    /* An empty bullet says nothing, so there is nothing to draw for. */
    expect(within(bullets).getAllByRole('button')).toHaveLength(2)

    await user.click(within(bullets).getByRole('button', { name: 'Then the violet one.' }))

    expect(pressedColour()).toBe('Violet')
    expect(within(bullets).getByRole('button', { name: 'Then the violet one.' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('offers no bullet picker for a step with no written bullets', () => {
    render(<Harness />)

    expect(screen.queryByRole('group', { name: 'Match a bullet' })).not.toBeInTheDocument()
  })

  it('lists the shapes so one can be selected and removed from the keyboard', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(
      <Harness
        initial={{
          ...IMAGE,
          annotations: [shape('a1'), shape('a2', { shape: 'arrow', color: 'light_blue' })],
        }}
        onChange={onChange}
      />,
    )

    const remove = screen.getByRole('button', { name: 'Delete shape' })
    expect(remove).toBeDisabled()

    const arrow = screen.getByRole('button', { name: '2. Light blue arrow' })
    arrow.focus()
    await user.keyboard('{Enter}')
    expect(arrow).toHaveAttribute('aria-pressed', 'true')

    await user.click(remove)

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ annotations: [expect.objectContaining({ id: 'a1' })] }),
    )
    expect(screen.queryByRole('button', { name: /arrow/ })).not.toBeInTheDocument()
  })

  it('removes the selected shape on Delete', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<Harness initial={{ ...IMAGE, annotations: [shape('a1')] }} onChange={onChange} />)

    await user.click(screen.getByRole('button', { name: '1. Red rectangle' }))
    fireEvent.keyDown(document.body, { key: 'Delete' })

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ annotations: [] }))
  })

  it('does not mistake Backspace in the description for deleting a shape', async () => {
    const user = userEvent.setup()
    render(<Harness initial={{ ...IMAGE, alt: 'Key switch', annotations: [shape('a1')] }} />)

    await user.click(screen.getByRole('button', { name: '1. Red rectangle' }))
    const description = screen.getByLabelText('Description')
    await user.click(description)
    await user.keyboard('{Backspace}{Backspace}')

    expect(description).toHaveValue('Key swit')
    expect(screen.getByRole('button', { name: '1. Red rectangle' })).toBeInTheDocument()
  })

  it('stores what the author says the picture shows', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<Harness onChange={onChange} />)

    await user.type(screen.getByLabelText('Description'), 'Laser key')

    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ alt: 'Laser key' }))
    expect(screen.getByRole('img')).toHaveAttribute('alt', 'Laser key')
  })
})

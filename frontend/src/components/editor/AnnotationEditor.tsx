/**
 * Draws and edits the shapes laid over a step image.
 *
 * Pointer events rather than mouse events, so this works with a finger on a
 * tablet at the microscope as well as with a mouse at a desk. Coordinates are
 * committed as fractions of the image, never pixels, so an annotation drawn on
 * a large screen still lands on the right place on a phone.
 */

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'

import { AnnotationShape, ANNOTATION_COLORS } from '../AnnotationOverlay'
import { commitDrag } from '../../domain/annotation'
import { newId } from '../../domain/guide'
import type { Annotation, Bullet, BulletColor, Media } from '../../domain/types'
import { useElementSize } from '../../hooks/useElementSize'
import { IconTrash } from '../icons'
import { Modal } from '../ui'

const COLORS: BulletColor[] = [
  'black',
  'red',
  'orange',
  'yellow',
  'green',
  'light_blue',
  'blue',
  'violet',
]

const SHAPES: { value: Annotation['shape']; label: string }[] = [
  { value: 'rectangle', label: 'Rectangle' },
  { value: 'ellipse', label: 'Ellipse' },
  { value: 'arrow', label: 'Arrow' },
]

const COLOR_NAMES: Record<BulletColor, string> = {
  black: 'Black',
  red: 'Red',
  orange: 'Orange',
  yellow: 'Yellow',
  green: 'Green',
  light_blue: 'Light blue',
  blue: 'Blue',
  violet: 'Violet',
}

/** Keys pressed while typing belong to the text, not to the drawing. */
function isTyping(target: EventTarget | null): boolean {
  return target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
}

interface AnnotationEditorProps {
  media: Media
  /**
   * The bullets of the step this image belongs to. A shape exists to point at
   * what one bullet is talking about, so the bullets are offered as the way to
   * choose its colour.
   */
  bullets: Bullet[]
  onChange: (media: Media) => void
  onClose: () => void
}

export function AnnotationEditor({ media, bullets, onChange, onClose }: AnnotationEditorProps) {
  const { ref, size } = useElementSize<HTMLDivElement>()
  const surfaceRef = useRef<HTMLDivElement>(null)

  const [shape, setShape] = useState<Annotation['shape']>('rectangle')
  const written = bullets.filter((bullet) => bullet.text.trim() !== '')
  /* Opens on the colour of the step's first coloured bullet — the likeliest
     thing to be pointed at — and on red when the step is all black, which
     disappears on the dark screenshots these mostly are. */
  const [color, setColor] = useState<BulletColor>(
    () => written.find((bullet) => bullet.color !== 'black')?.color ?? 'red',
  )
  const [drawing, setDrawing] = useState<Annotation | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const annotations = media.annotations

  const removeSelected = useCallback(() => {
    if (!selectedId) return
    onChange({ ...media, annotations: annotations.filter((item) => item.id !== selectedId) })
    setSelectedId(null)
  }, [annotations, media, onChange, selectedId])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTyping(event.target)) return
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedId) {
        event.preventDefault()
        removeSelected()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [removeSelected, selectedId])

  function fractionAt(event: ReactPointerEvent): { x: number; y: number } | null {
    const surface = surfaceRef.current
    if (!surface) return null
    const bounds = surface.getBoundingClientRect()
    if (bounds.width === 0 || bounds.height === 0) return null
    return {
      x: (event.clientX - bounds.left) / bounds.width,
      y: (event.clientY - bounds.top) / bounds.height,
    }
  }

  function onPointerDown(event: ReactPointerEvent) {
    /* A second finger, or a right click, is not the start of a shape. */
    if (drawing || (event.pointerType === 'mouse' && event.button !== 0)) return
    const origin = fractionAt(event)
    if (!origin) return

    event.currentTarget.setPointerCapture(event.pointerId)
    setSelectedId(null)
    setDrawing({ id: newId(), shape, color, x: origin.x, y: origin.y, width: 0, height: 0 })
  }

  function onPointerMove(event: ReactPointerEvent) {
    if (!drawing) return
    const position = fractionAt(event)
    if (!position) return
    setDrawing({ ...drawing, width: position.x - drawing.x, height: position.y - drawing.y })
  }

  function onPointerUp() {
    if (!drawing) return

    const stored = commitDrag(drawing)
    if (stored) {
      onChange({ ...media, annotations: [...annotations, stored] })
      setSelectedId(stored.id)
    }
    setDrawing(null)
  }

  return (
    <Modal title="Annotate image" onClose={onClose}>
      <div className="annotate">
        <div className="annotate__toolbar">
          <div className="annotate__group" role="group" aria-label="Shape">
            {SHAPES.map((option) => (
              <button
                key={option.value}
                type="button"
                className="button button--sm"
                aria-pressed={shape === option.value}
                onClick={() => setShape(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="swatches" role="group" aria-label="Colour">
            {COLORS.map((option) => (
              <button
                key={option}
                type="button"
                className="swatch"
                style={{ color: ANNOTATION_COLORS[option] }}
                aria-label={COLOR_NAMES[option]}
                title={COLOR_NAMES[option]}
                aria-pressed={color === option}
                onClick={() => setColor(option)}
              />
            ))}
          </div>

          <button
            type="button"
            className="button button--danger button--sm"
            disabled={!selectedId}
            onClick={removeSelected}
          >
            <IconTrash size={14} />
            Delete shape
          </button>
        </div>

        {written.length > 0 && (
          <div className="annotate__bullets" role="group" aria-label="Match a bullet">
            <span className="annotate__bullets-label">Draw for</span>
            {written.map((bullet) => (
              <button
                key={bullet.id}
                type="button"
                className="annotate__bullet"
                aria-pressed={bullet.color === color}
                title={bullet.text}
                onClick={() => setColor(bullet.color)}
              >
                <span
                  className="annotate__bullet-dot"
                  style={{ background: ANNOTATION_COLORS[bullet.color] }}
                />
                <span className="annotate__bullet-text">{bullet.text}</span>
              </button>
            ))}
          </div>
        )}

        <div className="annotate__surface" ref={surfaceRef}>
          <div className="annotated" ref={ref}>
            {/* The display copy: shapes are stored as fractions of the picture,
                so drawing on the smaller file puts them in the same place. */}
            <img
              src={media.displayUrl ?? media.url}
              alt={media.alt}
              draggable={false}
              decoding="async"
              width={media.width ?? undefined}
              height={media.height ?? undefined}
            />
            {size.width > 0 && (
              <svg
                className="annotated__overlay annotated__overlay--interactive"
                width={size.width}
                height={size.height}
                onPointerDown={onPointerDown}
                onPointerMove={onPointerMove}
                onPointerUp={onPointerUp}
                onPointerCancel={() => setDrawing(null)}
              >
                {annotations.map((annotation) => (
                  <g
                    key={annotation.id}
                    style={{ cursor: 'pointer' }}
                    onPointerDown={(event) => {
                      event.stopPropagation()
                      setSelectedId(annotation.id)
                    }}
                  >
                    <AnnotationShape
                      annotation={annotation}
                      width={size.width}
                      height={size.height}
                      selected={annotation.id === selectedId}
                    />
                  </g>
                ))}
                {drawing && (
                  <AnnotationShape
                    annotation={drawing}
                    width={size.width}
                    height={size.height}
                  />
                )}
              </svg>
            )}
          </div>
        </div>

        <p className="field__hint">
          Drag on the image to draw. Use the colour of the bullet the shape belongs to, so the
          instruction and the picture agree. Select a shape and press Delete to remove it.
        </p>

        {/* The shapes again, as buttons: on the picture they can only be picked
            with a pointer, and a keyboard user must be able to remove one too. */}
        {annotations.length > 0 && (
          <div className="annotate__shapes" role="group" aria-label="Shapes on this image">
            {annotations.map((annotation, index) => (
              <button
                key={annotation.id}
                type="button"
                className="annotate__shape"
                aria-pressed={annotation.id === selectedId}
                onClick={() =>
                  setSelectedId(annotation.id === selectedId ? null : annotation.id)
                }
              >
                <span
                  className="annotate__bullet-dot"
                  style={{ background: ANNOTATION_COLORS[annotation.color] }}
                />
                {index + 1}. {COLOR_NAMES[annotation.color]} {annotation.shape}
              </button>
            ))}
          </div>
        )}

        <div className="field">
          <label className="field__label" htmlFor="image-description">
            Description
          </label>
          <input
            id="image-description"
            className="input"
            value={media.alt}
            maxLength={1000}
            placeholder="e.g. The laser key switch on the front of the power supply"
            onChange={(event) => onChange({ ...media, alt: event.target.value })}
          />
          <span className="field__hint">
            What the picture shows, for someone who cannot see it. Read out by screen readers and
            shown if the image fails to load.
          </span>
        </div>

        <div className="page-actions">
          <button type="button" className="button button--primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Modal>
  )
}


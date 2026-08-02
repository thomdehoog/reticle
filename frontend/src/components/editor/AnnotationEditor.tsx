/**
 * Draws and edits the shapes laid over a step image.
 *
 * Pointer events rather than mouse events, so this works with a finger on a
 * tablet at the microscope as well as with a mouse at a desk. Coordinates are
 * committed as fractions of the image, never pixels, so an annotation drawn on
 * a large screen still lands on the right place on a phone.
 */

import {
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from 'react'

import { AnnotationShape, ANNOTATION_COLORS } from '../AnnotationOverlay'
import { isMeaningfulDrag, normaliseAnnotation } from '../../domain/annotation'
import { newId } from '../../domain/guide'
import type { Annotation, BulletColor, Media } from '../../domain/types'
import { BULLET_COLOR_ORDER } from '../../domain/palette'
import { useElementSize } from '../../hooks/useElementSize'
import { IconTrash } from '../icons'
import { Modal } from '../ui'

const COLORS = BULLET_COLOR_ORDER

const SHAPES: { value: Annotation['shape']; label: string }[] = [
  { value: 'rectangle', label: 'Rectangle' },
  { value: 'ellipse', label: 'Ellipse' },
  { value: 'arrow', label: 'Arrow' },
]

interface AnnotationEditorProps {
  media: Media
  onChange: (media: Media) => void
  onClose: () => void
}

export function AnnotationEditor({ media, onChange, onClose }: AnnotationEditorProps) {
  const { ref, size } = useElementSize<HTMLDivElement>()
  const surfaceRef = useRef<HTMLDivElement>(null)

  const [shape, setShape] = useState<Annotation['shape']>('rectangle')
  const [color, setColor] = useState<BulletColor>('red')
  const [drawing, setDrawing] = useState<Annotation | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const annotations = media.annotations

  function removeSelected() {
    if (!selectedId) return
    onChange({ ...media, annotations: annotations.filter((item) => item.id !== selectedId) })
    setSelectedId(null)
  }

  /**
   * Bound to the drawing surface, not to the document. On the document,
   * Backspace deletes the selected shape wherever the caret happens to be — so
   * an author correcting a typo in a text field, here or on the page behind
   * this dialog, silently loses an annotation instead of a character.
   */
  function onSurfaceKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Delete' && event.key !== 'Backspace') return
    if (!selectedId) return
    event.preventDefault()
    removeSelected()
  }

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

    /* Judged after normalisation, not before. A drag that happened largely
       outside the picture — easy enough once the pointer is captured — is big
       enough to keep while it is still raw, and collapses to nothing once it is
       clamped to the image. What got stored was an invisible zero-size shape
       that counted towards the annotation badge and could not be clicked, so it
       could not be deleted from the drawing surface either. */
    const finished = normaliseAnnotation(drawing)
    if (isMeaningfulDrag(finished)) {
      onChange({ ...media, annotations: [...annotations, finished] })
      setSelectedId(finished.id)
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
                aria-label={option.replace('_', ' ')}
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

        {/* Focusable so the keys above reach it, and focused by any touch or
            click on the picture, which is how a shape gets selected anyway. */}
        <div
          className="annotate__surface"
          ref={surfaceRef}
          role="group"
          aria-label="Drawing surface"
          tabIndex={0}
          onKeyDown={onSurfaceKeyDown}
          onPointerDown={() => surfaceRef.current?.focus()}
        >
          <div className="annotated" ref={ref}>
            <img src={media.url} alt={media.alt} draggable={false} />
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
          instruction and the picture agree. Select a shape and press Delete or Backspace to remove
          it.
        </p>

        <div className="page-actions">
          <button type="button" className="button button--primary" onClick={onClose}>
            Done
          </button>
        </div>
      </div>
    </Modal>
  )
}


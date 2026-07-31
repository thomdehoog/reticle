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
import { isMeaningfulDrag, normaliseAnnotation } from '../../domain/annotation'
import { newId } from '../../domain/guide'
import type { Annotation, BulletColor, Media } from '../../domain/types'
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

  const removeSelected = useCallback(() => {
    if (!selectedId) return
    onChange({ ...media, annotations: annotations.filter((item) => item.id !== selectedId) })
    setSelectedId(null)
  }, [annotations, media, onChange, selectedId])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
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

    if (isMeaningfulDrag(drawing)) {
      onChange({ ...media, annotations: [...annotations, normaliseAnnotation(drawing)] })
      setSelectedId(drawing.id)
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

        <div className="annotate__surface" ref={surfaceRef}>
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
          instruction and the picture agree. Select a shape and press Delete to remove it.
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


/**
 * Draws annotations over a step image.
 *
 * ZMB's guides lean on this: a bullet says "click the icon in the top left" and
 * the matching image carries a rectangle in the same colour. Losing that turns
 * a precise instruction into a vague one.
 *
 * The shapes are stored as fractions of the image and drawn into a pixel-sized
 * SVG, so nothing skews when the picture is scaled down on a phone, and the
 * original upload is never modified — annotations stay editable for ever.
 */

import { BULLET_COLOR_HEX } from '../domain/palette'
import type { Annotation } from '../domain/types'
import { useElementSize } from '../hooks/useElementSize'

/**
 * The shapes are drawn in the bullet palette itself, not in a lookalike of it.
 * A shape whose red is one shade off the red dot beside it stops reading as the
 * same instruction and starts reading as a second one.
 */
export const ANNOTATION_COLORS = BULLET_COLOR_HEX

const STROKE_WIDTH = 3

/**
 * Every shape is drawn twice: a white stroke underneath, the colour on top.
 *
 * Annotations land on screenshots of instrument software, and half of those are
 * near-black — a LAS X or ZEN acquisition window. Against that, the black
 * annotation colour measures about 1.01:1 and simply disappears, and the rest
 * sit at a marginal 3.2:1. The halo makes the whole palette legible over any
 * photograph, light or dark, and survives greyscale printing.
 */
const HALO_WIDTH = STROKE_WIDTH + 3
const HALO_COLOR = '#ffffff'

export function AnnotationShape({
  annotation,
  width,
  height,
  selected = false,
}: {
  annotation: Annotation
  width: number
  height: number
  selected?: boolean
}) {
  const stroke = ANNOTATION_COLORS[annotation.color]
  const x = annotation.x * width
  const y = annotation.y * height
  const w = annotation.width * width
  const h = annotation.height * height

  const geometry = {
    fill: 'none',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
  const halo = { ...geometry, stroke: HALO_COLOR, strokeWidth: HALO_WIDTH, opacity: 0.85 }
  const common = { ...geometry, stroke, strokeWidth: STROKE_WIDTH }

  const highlight = selected ? (
    <rect
      x={Math.min(x, x + w) - 4}
      y={Math.min(y, y + h) - 4}
      width={Math.abs(w) + 8}
      height={Math.abs(h) + 8}
      fill="none"
      stroke={stroke}
      strokeWidth={1}
      strokeDasharray="4 3"
      opacity={0.9}
    />
  ) : null

  if (annotation.shape === 'rectangle') {
    const box = {
      x: Math.min(x, x + w),
      y: Math.min(y, y + h),
      width: Math.abs(w),
      height: Math.abs(h),
      rx: 2,
    }
    return (
      <g>
        <rect {...box} {...halo} />
        <rect {...box} {...common} />
        {highlight}
      </g>
    )
  }

  if (annotation.shape === 'ellipse') {
    const oval = {
      cx: x + w / 2,
      cy: y + h / 2,
      rx: Math.abs(w) / 2,
      ry: Math.abs(h) / 2,
    }
    return (
      <g>
        <ellipse {...oval} {...halo} />
        <ellipse {...oval} {...common} />
        {highlight}
      </g>
    )
  }

  const angle = Math.atan2(h, w)
  const headLength = Math.min(16, Math.hypot(w, h) * 0.35)
  const spread = 0.42

  const shaft = { x1: x, y1: y, x2: x + w, y2: y + h }
  const head = {
    points: [
      `${x + w - headLength * Math.cos(angle - spread)},${y + h - headLength * Math.sin(angle - spread)}`,
      `${x + w},${y + h}`,
      `${x + w - headLength * Math.cos(angle + spread)},${y + h - headLength * Math.sin(angle + spread)}`,
    ].join(' '),
  }

  return (
    <g>
      <line {...shaft} {...halo} />
      <polyline {...head} {...halo} />
      <line {...shaft} {...common} />
      <polyline {...head} {...common} />
      {highlight}
    </g>
  )
}

/**
 * An image with its annotations drawn on top. Used by the reader; the editor
 * layers its own drawing surface over the same geometry.
 */
export function AnnotatedImage({
  src,
  alt,
  annotations,
  className,
}: {
  src: string
  alt: string
  annotations: Annotation[]
  className?: string
}) {
  const { ref, size } = useElementSize<HTMLDivElement>()

  return (
    <div className={`annotated${className ? ` ${className}` : ''}`} ref={ref}>
      <img src={src} alt={alt} loading="lazy" />
      {annotations.length > 0 && size.width > 0 && (
        <svg
          className="annotated__overlay"
          width={size.width}
          height={size.height}
          aria-hidden="true"
        >
          {annotations.map((annotation) => (
            <AnnotationShape
              key={annotation.id}
              annotation={annotation}
              width={size.width}
              height={size.height}
            />
          ))}
        </svg>
      )}
    </div>
  )
}

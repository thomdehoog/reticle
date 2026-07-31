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

import type { Annotation, BulletColor } from '../domain/types'
import { useElementSize } from '../hooks/useElementSize'

/** Matches the bullet palette, so a shape reads as belonging to its bullet. */
export const ANNOTATION_COLORS: Record<BulletColor, string> = {
  black: '#1f2328',
  red: '#d1242f',
  orange: '#bc4c00',
  yellow: '#9a6700',
  green: '#1a7f37',
  light_blue: '#249fd6',
  blue: '#0969da',
  violet: '#8250df',
}

const STROKE_WIDTH = 3

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

  const common = {
    stroke,
    strokeWidth: STROKE_WIDTH,
    fill: 'none',
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }

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
    return (
      <g>
        <rect
          x={Math.min(x, x + w)}
          y={Math.min(y, y + h)}
          width={Math.abs(w)}
          height={Math.abs(h)}
          rx={2}
          {...common}
        />
        {highlight}
      </g>
    )
  }

  if (annotation.shape === 'ellipse') {
    return (
      <g>
        <ellipse
          cx={x + w / 2}
          cy={y + h / 2}
          rx={Math.abs(w) / 2}
          ry={Math.abs(h) / 2}
          {...common}
        />
        {highlight}
      </g>
    )
  }

  const angle = Math.atan2(h, w)
  const headLength = Math.min(16, Math.hypot(w, h) * 0.35)
  const spread = 0.42

  return (
    <g>
      <line x1={x} y1={y} x2={x + w} y2={y + h} {...common} />
      <polyline
        points={[
          `${x + w - headLength * Math.cos(angle - spread)},${y + h - headLength * Math.sin(angle - spread)}`,
          `${x + w},${y + h}`,
          `${x + w - headLength * Math.cos(angle + spread)},${y + h - headLength * Math.sin(angle + spread)}`,
        ].join(' ')}
        {...common}
      />
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

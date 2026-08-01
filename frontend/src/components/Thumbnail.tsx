/**
 * The picture on a browse card, and what stands in when there is not one yet.
 *
 * Browsing Reticle is meant to be looked at rather than read. Somebody heading
 * for the confocal recognises the instrument well before they have finished
 * reading its name, and a facility's documentation is mostly pictures anyway —
 * so the route to a guide or a wiki page is built from images, and the words on
 * the way there are kept to what identifies the destination.
 *
 * The fallback matters as much as the photograph. A card with a missing image
 * reads as broken, and a grey rectangle reads as unfinished; both undo the
 * point of a visual index. So a destination with no picture gets a drawn one,
 * derived from its own name: the same name always produces the same figure, so
 * a section stays recognisable from visit to visit even before anybody has
 * uploaded a photograph of it.
 *
 * All of this artwork is original — concentric rings and a cross, after the
 * etched reticle the project is named for.
 */

const HUES = [198, 172, 262, 14, 340, 44, 152, 218, 288, 96]

/**
 * A small, stable hash. Not a cryptographic one and not trying to be: it only
 * has to spread names across the palette and give the same answer every time.
 */
function hashOf(value: string): number {
  let hash = 0
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) >>> 0
  }
  return hash
}

export interface ThumbnailProps {
  /** What identifies the destination — its name or title. */
  seed: string
  src?: string | null
  alt?: string
  /** A short mark drawn over the figure, usually the first letters of the name. */
  badge?: string
  className?: string
}

/** The first letters of the first two words: enough to tell tiles apart. */
export function monogram(value: string): string {
  const words = value
    .trim()
    .split(/\s+/)
    .filter((word) => /[\p{L}\p{N}]/u.test(word))
  if (words.length === 0) return '·'
  const letters = words.slice(0, 2).map((word) => Array.from(word)[0].toUpperCase())
  return letters.join('')
}

export function DrawnFigure({ seed, label }: { seed: string; label?: string }) {
  const hash = hashOf(seed)
  const hue = HUES[hash % HUES.length]
  const second = HUES[(hash >> 3) % HUES.length]

  /*
   * The viewBox is the card's own proportion rather than a square. A square one
   * cropped to a 16:10 tile cut the bottom off the drawing, which took the
   * monogram with it — the figure has to be composed at the shape it is
   * actually shown at.
   *
   * Two rings and a cross, placed from the same hash, so a section's figure is
   * recognisably its own rather than a generic ornament.
   */
  const centreX = 44 + (hash % 60)
  const centreY = 22 + ((hash >> 5) % 46)
  const radius = 26 + ((hash >> 9) % 12)

  return (
    <svg
      className="thumb__figure"
      viewBox="0 0 160 100"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={`reticle-figure-${hash}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={`hsl(${hue} 56% 32%)`} />
          <stop offset="100%" stopColor={`hsl(${second} 52% 19%)`} />
        </linearGradient>
      </defs>
      <rect width="160" height="100" fill={`url(#reticle-figure-${hash})`} />
      <g stroke="rgba(255,255,255,0.26)" fill="none" strokeWidth="1">
        <circle cx={centreX} cy={centreY} r={radius} />
        <circle cx={centreX} cy={centreY} r={radius * 0.55} />
        <line x1={centreX - radius - 14} y1={centreY} x2={centreX + radius + 14} y2={centreY} />
        <line x1={centreX} y1={centreY - radius - 14} x2={centreX} y2={centreY + radius + 14} />
      </g>
      <circle cx={centreX} cy={centreY} r="2.4" fill="rgba(255,255,255,0.45)" />
      {label && (
        <text
          x="10"
          y="88"
          fill="rgba(255,255,255,0.82)"
          fontSize="19"
          fontWeight="700"
          letterSpacing="0.5"
          fontFamily="inherit"
        >
          {label}
        </text>
      )}
    </svg>
  )
}

export function Thumbnail({ seed, src, alt = '', badge, className }: ThumbnailProps) {
  return (
    <span className={`thumb${className ? ` ${className}` : ''}`}>
      {src ? (
        <img className="thumb__image" src={src} alt={alt} loading="lazy" />
      ) : (
        <DrawnFigure seed={seed} label={badge ?? monogram(seed)} />
      )}
    </span>
  )
}

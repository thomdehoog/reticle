/**
 * Original icon set for Reticle, drawn as inline SVG.
 *
 * These are our own paths — no third-party icon library or asset is used
 * anywhere in this project (see NOTICE.md). Inline SVG also means no icon-font
 * request and no flash of missing glyphs on a slow ZMB network share.
 */

interface IconProps {
  size?: number
  className?: string
  title?: string
}

function svgProps({ size = 16, className, title }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    role: title ? ('img' as const) : ('presentation' as const),
    'aria-hidden': title ? undefined : true,
    'aria-label': title,
  }
}

/** The Reticle mark: a circle crossed by eyepiece graticule lines. */
export function ReticleMark({ size = 22, className }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" className={className} aria-hidden="true">
      <circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <circle cx="12" cy="12" r="2.4" fill="currentColor" />
      <path
        d="M12 0.8v5.4M12 17.8v5.4M0.8 12h5.4M17.8 12h5.4"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function IconNote(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" />
      <path d="M12 7.6h.01" />
    </svg>
  )
}

export function IconCaution(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 3.6 21.4 20H2.6L12 3.6Z" />
      <path d="M12 10v4" />
      <path d="M12 17.4h.01" />
    </svg>
  )
}

export function IconWarning(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M8.4 2.9h7.2L21.1 8.4v7.2l-5.5 5.5H8.4l-5.5-5.5V8.4L8.4 2.9Z" />
      <path d="M12 8v4.6" />
      <path d="M12 16.2h.01" />
    </svg>
  )
}

export function IconReminder(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6 3.6h12v17.2l-6-4.3-6 4.3V3.6Z" />
    </svg>
  )
}

export function IconPlus(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function IconTrash(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 7h16" />
      <path d="M9.5 7V4.8h5V7" />
      <path d="M6.4 7l.9 12.2h9.4L17.6 7" />
      <path d="M10.2 10.6v5.4M13.8 10.6v5.4" />
    </svg>
  )
}

export function IconDrag(props: IconProps) {
  return (
    <svg {...svgProps(props)} strokeWidth={2.4}>
      <path d="M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01" />
    </svg>
  )
}

export function IconSearch(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.4 15.4 20 20" />
    </svg>
  )
}

export function IconClose(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  )
}

export function IconChevronUp(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6 14.5 12 8.5l6 6" />
    </svg>
  )
}

export function IconChevronDown(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M6 9.5 12 15.5l6-6" />
    </svg>
  )
}

export function IconIndentRight(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M10 6h10M10 12h10M10 18h10" />
      <path d="M3.5 9.5 6.5 12l-3 2.5V9.5Z" fill="currentColor" />
    </svg>
  )
}

export function IconIndentLeft(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M10 6h10M10 12h10M10 18h10" />
      <path d="M6.5 9.5 3.5 12l3 2.5V9.5Z" fill="currentColor" />
    </svg>
  )
}

export function IconPalette(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <circle cx="12" cy="12" r="9" />
      <circle cx="9" cy="9.5" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="15" cy="9.5" r="1.4" fill="currentColor" stroke="none" />
      <circle cx="12" cy="15" r="1.4" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function IconImage(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <rect x="3" y="4.5" width="18" height="15" rx="2" />
      <circle cx="8.6" cy="10" r="1.6" />
      <path d="m4 17 4.8-4.4 3.6 3.2 3-2.6L20 17" />
    </svg>
  )
}

export function IconPrint(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M7 9V3.5h10V9" />
      <path d="M7 18H5.2A2.2 2.2 0 0 1 3 15.8v-4.6A2.2 2.2 0 0 1 5.2 9h13.6A2.2 2.2 0 0 1 21 11.2v4.6a2.2 2.2 0 0 1-2.2 2.2H17" />
      <path d="M7 14.5h10v6H7z" />
    </svg>
  )
}

export function IconEdit(props: IconProps) {
  return (
    <svg {...svgProps(props)}>
      <path d="M4 20h4.2L19 9.2a2.1 2.1 0 0 0 0-3l-1.2-1.2a2.1 2.1 0 0 0-3 0L4 15.8V20Z" />
      <path d="M14.2 6.6 17.4 9.8" />
    </svg>
  )
}

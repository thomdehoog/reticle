import { useEffect, useRef, useState } from 'react'

export interface Size {
  width: number
  height: number
}

/**
 * Tracks an element's rendered pixel size.
 *
 * Annotations are stored as fractions of the image so they survive any display
 * size, but drawing them needs real pixels: an SVG stretched with
 * `preserveAspectRatio="none"` would skew arrowheads and stroke widths along
 * with the geometry. Measuring instead keeps circles round on a phone.
 */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, setSize] = useState<Size>({ width: 0, height: 0 })

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      const { width, height } = entry.contentRect
      setSize((current) =>
        current.width === width && current.height === height ? current : { width, height },
      )
    })

    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return { ref, size }
}

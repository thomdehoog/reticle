/**
 * Measuring how big something actually is on screen.
 *
 * Annotations are stored as fractions of the image so they survive any display
 * size, but drawing them needs real pixels: an SVG stretched with
 * `preserveAspectRatio="none"` skews arrowheads and stroke widths along with
 * the geometry, so a circle drawn on a desktop becomes an oval on a phone.
 * Measuring the element instead keeps the shapes the shape they were drawn.
 *
 * It is its own file because the reader's overlay and the editor's drawing
 * surface both need it, and because a ResizeObserver has a subscription to tear
 * down and a re-render to avoid on an unchanged size — the kind of detail that
 * is right once here and wrong in half the copies otherwise.
 */

import { useEffect, useRef, useState } from 'react'

export interface Size {
  width: number
  height: number
}

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

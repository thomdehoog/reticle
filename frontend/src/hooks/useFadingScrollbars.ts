/**
 * Show a scrollbar while it is being used, and not otherwise.
 *
 * A scrollbar answers one question — how far down am I — and it is only asked
 * while moving. Parked permanently down the side of both columns it is a rule
 * of colour on every screen, saying nothing, next to photographs that are the
 * whole point of the page. macOS hides them like this natively; Windows and
 * Linux do not, which is where this site is read.
 *
 * The track keeps its width the whole time and only the thumb fades. Hiding the
 * bar itself would reflow the column every time somebody started scrolling —
 * text reflowing under a reader's eyes to announce that they are reading is
 * worse than the bar was.
 *
 * One listener for the whole document rather than a hook per scrolling box:
 * `scroll` does not bubble, but it does capture, so the document sees every one
 * of them — the rail, the article, a modal, a wide code block — and each is
 * marked and cleared on its own timer. A component that adds a scrolling box
 * later needs to do nothing, which is the point: the one that gets forgotten is
 * the one nobody remembered to wire up.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { useEffect } from 'react'

/** How long the thumb stays after the last scroll event. */
const LINGER_MS = 900

export function useFadingScrollbars() {
  useEffect(() => {
    /* Per element, so scrolling the article does not clear the rail's mark —
       and weak, so a box that is removed from the page is not held alive by a
       pending timer. */
    const timers = new WeakMap<Element, number>()

    function onScroll(event: Event) {
      const target = event.target
      /* Scrolling the page itself reports the document; the element wearing the
         scrollbar there is the root. */
      const element =
        target instanceof Document ? target.documentElement : target instanceof Element ? target : null
      if (!element) return

      element.setAttribute('data-scrolling', '')

      const pending = timers.get(element)
      if (pending !== undefined) window.clearTimeout(pending)
      timers.set(
        element,
        window.setTimeout(() => {
          element.removeAttribute('data-scrolling')
          timers.delete(element)
        }, LINGER_MS),
      )
    }

    document.addEventListener('scroll', onScroll, { capture: true, passive: true })
    return () => document.removeEventListener('scroll', onScroll, { capture: true })
  }, [])
}

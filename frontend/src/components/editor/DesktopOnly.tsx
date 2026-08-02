/**
 * Writing a guide needs a screen. This says so, on the ones that are too small.
 *
 * Reading a procedure at the bench on a phone is the whole point of Reticle,
 * and every reader screen is built for it. Writing one is the opposite job:
 * four pictures beside their instructions, shapes drawn on a screenshot, thirty
 * steps reordered. Shrinking that into 390px produces a version of the editor
 * that technically responds to every tap and that nobody can actually author
 * in — and it costs a set of phone layouts to maintain for a screen no author
 * chooses to use.
 *
 * So the small-screen editor is one sentence instead. An author who taps Edit
 * on the tram is told to come back at a desk, which is what they were going to
 * do anyway, rather than being handed a form that will waste ten minutes first.
 *
 * The breakpoint is the stylesheet's, not this component's: it renders both and
 * lets `@media` decide, so there is no width in the JavaScript to drift from
 * the width in the CSS, and no resize listener re-rendering an editor.
 */

import type { ReactNode } from 'react'

export function DesktopOnly({ what, children }: { what: string; children: ReactNode }) {
  return (
    <>
      <p className="desktop-only">
        Open this on a computer to edit {what}. The screen here is too narrow to place pictures
        beside their instructions, which is most of what editing is.
      </p>
      <div className="desktop-only__work">{children}</div>
    </>
  )
}

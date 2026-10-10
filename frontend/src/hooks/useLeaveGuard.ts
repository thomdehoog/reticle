import { useBlocker } from '@tanstack/react-router'

import type { Autosave } from './useAutosave'

/**
 * Asks before leaving an editor whose changes the server has refused.
 *
 * Ordinarily leaving needs no question: `useAutosave` sends whatever is unsaved
 * on the way out. That only works while a save can succeed. After a conflict,
 * or a save the server keeps rejecting, the copy on screen is the only one
 * there is — and a click on a breadcrumb would discard it without a word.
 *
 * Only navigation inside the app is handled here; closing the tab is the
 * autosave's own `beforeunload` warning.
 */
export function useLeaveGuard(autosave: Pick<Autosave<unknown>, 'saveState' | 'conflicted'>): void {
  const stuck = autosave.saveState === 'error' || autosave.conflicted

  useBlocker({
    disabled: !stuck,
    enableBeforeUnload: false,
    shouldBlockFn: () =>
      !window.confirm('Your latest changes have not been saved. Leave and discard them?'),
  })
}

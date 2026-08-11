/**
 * Setup that runs before every test file.
 */

import '@testing-library/jest-dom/vitest'

/**
 * jsdom implements no layout, so it has no ResizeObserver. Components that
 * measure themselves — the annotation overlay sizes its canvas from the
 * rendered image — would otherwise throw on render and take unrelated
 * assertions down with them.
 *
 * The stub reports nothing rather than faking a size: geometry is covered by
 * the pure tests in `domain/annotation.test.ts`, where it can be asserted
 * exactly instead of inferred from a fictional layout.
 */
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub implements ResizeObserver {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  globalThis.ResizeObserver = ResizeObserverStub
}

/**
 * jsdom draws nothing, so a Range has no client rectangles. ProseMirror reads
 * them when the wiki editor takes focus or places its caret, and the missing
 * function surfaced as an uncaught error inside a timer — after the assertions
 * passed, which is exactly the kind of noise that becomes a flake. Empty is
 * the honest answer a layoutless DOM can give.
 */
if (typeof Range !== 'undefined' && !Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => ({
    length: 0,
    item: () => null,
    [Symbol.iterator]: [][Symbol.iterator],
  }) as unknown as DOMRectList
  Range.prototype.getBoundingClientRect = () =>
    ({ x: 0, y: 0, top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 }) as DOMRect
}

/**
 * jsdom has no media queries either, and the header asks whether it is in its
 * phone layout. The stub answers "no" so tests get the wide layout by default,
 * which is the one most of them are about. A test that wants the phone header
 * replaces `window.matchMedia` itself and says so.
 */
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (media: string) =>
    ({
      media,
      matches: false,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

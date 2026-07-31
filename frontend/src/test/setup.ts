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

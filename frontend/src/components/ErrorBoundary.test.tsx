import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'

/**
 * The failure this guards is not subtle: without a boundary React unmounts the
 * whole tree and the tab goes white. What makes it worth a test is that the
 * blank screen only appears when something *else* is already broken, so it is
 * exactly the code path nobody exercises until a reader is standing at a
 * microscope looking at nothing.
 */

function Explodes({ message = 'annotation has no shape' }: { message?: string }): never {
  throw new Error(message)
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // React logs caught render errors to console.error regardless, and the
    // boundary adds its own. Silencing keeps the test output readable without
    // hiding a real failure — the assertions below still run.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows a message instead of a blank page when a child throws', () => {
    render(
      <ErrorBoundary>
        <Explodes />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toBeInTheDocument()
    expect(screen.getByText(/Reticle stopped responding/i)).toBeInTheDocument()
  })

  it('renders its children untouched when nothing goes wrong', () => {
    render(
      <ErrorBoundary>
        <p>Focus the sample before increasing laser power.</p>
      </ErrorBoundary>,
    )

    expect(screen.getByText(/Focus the sample/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says one page failed rather than the whole system, when scoped to content', () => {
    render(
      <ErrorBoundary scope="content">
        <Explodes />
      </ErrorBoundary>,
    )

    expect(screen.getByText(/This page could not be displayed/i)).toBeInTheDocument()
    expect(screen.getByText(/Other guides are unaffected/i)).toBeInTheDocument()
  })

  it('warns that recent edits may not have been saved', () => {
    /* The tempting wording is "your work is safe". It is not known to be, and
       an author who trusts that and closes the tab loses it for real. */
    render(
      <ErrorBoundary>
        <Explodes />
      </ErrorBoundary>,
    )

    expect(screen.getByText(/may not have been saved/i)).toBeInTheDocument()
  })

  it('offers a real page load as the way out', () => {
    render(
      <ErrorBoundary>
        <Explodes />
      </ErrorBoundary>,
    )

    expect(screen.getByRole('button', { name: /reload/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /start/i })).toHaveAttribute('href', '/')
  })

  it('puts the failure in the console for whoever is asked to look', () => {
    render(
      <ErrorBoundary>
        <Explodes message="annotation has no shape" />
      </ErrorBoundary>,
    )

    const logged = (console.error as unknown as ReturnType<typeof vi.fn>).mock.calls
    expect(
      logged.some((call: unknown[]) => String(call[0]).includes('failed to render')),
    ).toBe(true)
  })

  it('exposes the thrown message without dumping a stack at the reader', () => {
    render(
      <ErrorBoundary>
        <Explodes message="annotation has no shape" />
      </ErrorBoundary>,
    )

    expect(screen.getByText('annotation has no shape')).toBeInTheDocument()
    expect(screen.getByText(/technical detail/i)).toBeInTheDocument()
  })
})

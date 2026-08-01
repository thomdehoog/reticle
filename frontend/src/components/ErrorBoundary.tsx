import { Component, type ErrorInfo, type ReactNode } from 'react'

/**
 * The last thing between a rendering bug and a white screen.
 *
 * React unmounts the entire tree when a render throws and nothing catches it.
 * There is no message, no navigation and no back button that helps — the tab is
 * simply blank, which reads as "the system is down" rather than "one guide has
 * something odd in it". For documentation somebody is standing at an instrument
 * trying to follow, that difference decides whether they retry or give up.
 *
 * Two deliberate choices:
 *
 * **Reset on navigation is not offered.** A boundary that silently re-renders
 * the same broken subtree loops. The escape here is a real page load, which also
 * discards whatever corrupt client state caused it.
 *
 * **It does not claim unsaved work is safe.** The editor autosaves, but a crash
 * mid-edit may have lost the last few seconds, and telling somebody their work
 * is fine when it may not be is worse than saying nothing. The wording states
 * what is known and no more.
 */

interface Props {
  children: ReactNode
  /** Distinguishes an editor crash from a whole-application one. */
  scope?: 'app' | 'content'
}

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The browser console is the only reporter this installation has. It is
    // what somebody will be asked to open when they report the page went
    // blank, so the component stack has to be in it rather than only React's
    // own warning.
    console.error('Reticle: a component failed to render.', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    const scope = this.props.scope ?? 'app'

    return (
      <div className="crash" role="alert">
        <h1 className="crash__title">
          {scope === 'content' ? 'This page could not be displayed' : 'Reticle stopped responding'}
        </h1>
        <p className="crash__body">
          Something in the page failed to render. This is a fault in Reticle, not
          something you did.
          {scope === 'content'
            ? ' Other guides are unaffected — go back and open a different one.'
            : ''}
        </p>
        <p className="crash__body">
          If you were part-way through editing, check your work after reloading:
          the last few seconds may not have been saved.
        </p>
        <div className="crash__actions">
          <button className="button button--primary" onClick={() => window.location.reload()}>
            Reload the page
          </button>
          <a className="button" href="/">
            Go to the start
          </a>
        </div>
        <details className="crash__details">
          <summary>Technical detail</summary>
          <pre className="crash__stack">{error.message}</pre>
        </details>
      </div>
    )
  }
}

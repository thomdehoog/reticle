/**
 * The safety net under the whole interface.
 *
 * If any part of React fails while drawing the page, React's response is to
 * remove everything - the tab simply goes white, with no message and no way back.
 * For somebody standing at a microscope following a procedure, that looks like
 * the whole system is down rather than one guide having something odd in it.
 *
 * This file catches that failure and shows a page explaining what happened, with
 * a way out. It also quietly tells the server, so the bug reaches somebody who
 * can fix it instead of living in a browser console nobody opens.
 */

import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Distinguishes an editor crash from a whole-application one. */
  scope?: 'app' | 'content'
}

/**
 * Sends the failure to the server, so it lands in the same log stream as
 * everything else with a request id attached.
 *
 * Plain `fetch` rather than the application's own `ApiClient`, deliberately.
 * This runs at the moment something in the application has already failed, and
 * routing the report through a layer that may itself be the broken thing is how
 * a crash reporter becomes the reason a crash goes unreported. Nothing here
 * depends on React, on context, or on any module that a rendering bug could
 * have taken down.
 *
 * Failure is swallowed for the same reason: if reporting throws, the user must
 * still see the message telling them what happened.
 */
async function report(error: Error, componentStack: string): Promise<void> {
  try {
    const csrf = document.cookie.match(/(?:^|;\s*)reticle_csrf=([^;]*)/)
    await fetch('/api/client-errors', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRF-Token': decodeURIComponent(csrf[1]) } : {}),
      },
      body: JSON.stringify({
        // Only the message and the stack. Not the URL's query string, which on
        // this application carries search terms, and nothing scooped from the
        // surrounding page — a crash report that collects local state
        // eventually collects a password somebody was typing.
        message: error.message.slice(0, 500),
        componentStack: componentStack.slice(0, 4000),
        url: window.location.pathname,
      }),
    })
  } catch {
    // Nothing to do. The screen below is what the user needs.
  }
}

interface State {
  error: Error | null
}

/**
 * Two deliberate choices worth knowing before changing this.
 *
 * **There is no "try again" button.** Re-drawing the same broken thing in place
 * would just fail again, in a loop. The way out is a real page reload, which
 * also throws away whatever confused state caused it.
 *
 * **It does not promise your work is safe.** The editor saves by itself, but a
 * crash may have lost the last few seconds, and telling somebody their work is
 * fine when it might not be is worse than saying nothing.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // The console is for whoever is sitting in front of it; the report is for
    // whoever has to fix it. A console message alone reaches a developer as
    // "it did not work this morning", if at all.
    console.error('Reticle: a component failed to render.', error, info.componentStack)
    void report(error, info.componentStack ?? '')
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

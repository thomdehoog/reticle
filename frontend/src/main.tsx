/**
 * The very first thing that runs in the browser.
 *
 * When somebody opens Reticle, the browser loads one mostly-empty HTML page and
 * then runs this file. It finds the empty box in that page and tells React to
 * draw the whole application inside it.
 *
 * The three wrappers around the app each add one thing everything else can then
 * rely on: a crash screen, so a bug shows a message instead of a blank tab; the
 * router, which decides which page to show for the address in the bar; and the
 * sign-in state, so every screen knows who is looking at it.
 */

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { App } from './App'
import { AuthProvider } from './auth/AuthContext'
import { ErrorBoundary } from './components/ErrorBoundary'
import './styles/app.css'

const container = document.getElementById('root')
if (!container) throw new Error('Reticle could not start: #root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
)

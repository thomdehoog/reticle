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

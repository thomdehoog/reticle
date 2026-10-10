import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { AppProviders } from './app/AppProviders'
import { createReticleApp } from './app/createApp'
import './styles/app.css'

const container = document.getElementById('root')
if (!container) throw new Error('Reticle could not start: #root is missing from index.html')

const app = createReticleApp()

createRoot(container).render(
  <StrictMode>
    <AppProviders app={app}>
      <App app={app} />
    </AppProviders>
  </StrictMode>,
)

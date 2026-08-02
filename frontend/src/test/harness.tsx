import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router'

import { AuthProvider } from '../auth/AuthContext'

/** Mounts a component tree with a session backed by the in-memory fake server. */
export function renderWithApp(
  ui: ReactNode,
  { route = '/', fetchImpl }: { route?: string; fetchImpl: typeof fetch },
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider fetchImpl={fetchImpl}>{ui}</AuthProvider>
    </MemoryRouter>,
  )
}

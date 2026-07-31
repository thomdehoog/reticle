import { useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { ReticleMark } from '../components/icons'

/**
 * The only screen an unauthenticated visitor can reach.
 *
 * Failures are reported in the same words regardless of whether the address is
 * unknown or the password was wrong, so the form cannot be used to discover who
 * has an account at ZMB.
 */
export function LoginPage() {
  const { login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      await login(email.trim(), password)
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'rate_limited') {
        setError('Too many attempts. Please wait a minute before trying again.')
      } else if (cause instanceof ApiError && cause.isTransient) {
        setError('Could not reach the Reticle server. Check your connection and try again.')
      } else {
        setError('Email or password is incorrect.')
      }
      setPassword('')
      setSubmitting(false)
    }
  }

  return (
    <div className="login">
      <form className="login__panel" onSubmit={onSubmit}>
        <div className="login__brand">
          <ReticleMark size={26} />
          Reticle
        </div>
        <p className="login__tagline">
          Guides and standard procedures — Center for Microscopy and Image Analysis, UZH
        </p>

        {error && (
          <div className="login__error" role="alert">
            {error}
          </div>
        )}

        <div className="field">
          <label className="field__label" htmlFor="login-email">
            Email
          </label>
          <input
            id="login-email"
            className="input"
            type="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="login-password">
            Password
          </label>
          <input
            id="login-password"
            className="input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        <button className="button button--primary" type="submit" disabled={submitting}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}

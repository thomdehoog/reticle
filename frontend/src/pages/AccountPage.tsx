/**
 * Your own account: your name, and changing your password.
 *
 * Deliberately small. This is the one screen every user reaches regardless of
 * role, so it does only what it says. Managing *other* people's accounts is a
 * different screen, for administrators.
 *
 * New colleagues are created with an initial password handed to them by an
 * admin, so a place to change it is not optional — without one, that first
 * shared secret stays valid indefinitely.
 */

import { useState, type FormEvent } from 'react'

import { ApiError } from '../api/client'
import { useApi, useAuth } from '../auth/AuthContext'
import { ErrorAlert } from '../components/ui'

const MINIMUM_PASSWORD_LENGTH = 12

const ROLE_DESCRIPTIONS = {
  viewer: 'You can read published guides.',
  author: 'You can write, edit and publish guides.',
  admin: 'You can write and publish guides, and manage people and categories.',
} as const

export function AccountPage() {
  const api = useApi()
  const { user } = useAuth()

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  if (!user) return null

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setLocalError(null)
    setDone(false)

    if (newPassword.length < MINIMUM_PASSWORD_LENGTH) {
      setLocalError(`Choose a password of at least ${MINIMUM_PASSWORD_LENGTH} characters.`)
      return
    }
    if (newPassword !== confirmation) {
      setLocalError('The two new passwords do not match.')
      return
    }

    setSubmitting(true)
    try {
      await api.changePassword(user!.id, currentPassword, newPassword)
      setDone(true)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'invalid_credentials') {
        setLocalError('Your current password is not correct.')
      } else {
        setError(cause)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Your account</h1>
          <p className="page-header__sub">
            {user.displayName} · {user.email}
          </p>
        </div>
      </div>

      <div className="card" style={{ maxWidth: 520 }}>
        <div className="card__body">
          <p style={{ color: 'var(--ink-500)', fontSize: '0.9rem' }}>
            {ROLE_DESCRIPTIONS[user.role]}
          </p>

          <h2 style={{ margin: '1.25rem 0 0.75rem' }}>Change password</h2>

          <form onSubmit={onSubmit}>
            <ErrorAlert error={error} />
            {localError && (
              <div className="alert alert--error" role="alert">
                {localError}
              </div>
            )}
            {done && (
              <div className="alert alert--info" role="status">
                Your password has been changed.
              </div>
            )}

            <div className="field">
              <label className="field__label" htmlFor="current-password">
                Current password
              </label>
              <input
                id="current-password"
                className="input"
                type="password"
                autoComplete="current-password"
                required
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </div>

            <div className="field">
              <label className="field__label" htmlFor="new-password">
                New password
              </label>
              <input
                id="new-password"
                className="input"
                type="password"
                autoComplete="new-password"
                required
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
              <span className="field__hint">
                At least {MINIMUM_PASSWORD_LENGTH} characters. A short phrase you can remember beats
                a short string you cannot.
              </span>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="confirm-password">
                Repeat new password
              </label>
              <input
                id="confirm-password"
                className="input"
                type="password"
                autoComplete="new-password"
                required
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
              />
            </div>

            <button className="button button--primary" type="submit" disabled={submitting}>
              {submitting ? 'Changing…' : 'Change password'}
            </button>
          </form>
        </div>
      </div>
    </>
  )
}

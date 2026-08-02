/**
 * Where an administrator manages accounts.
 *
 * Creating accounts, changing what somebody is allowed to do, and deactivating
 * people who have left. Deactivating rather than deleting: guides record who
 * wrote them, and a departed colleague's name should stay on the procedure they
 * wrote.
 */

import { useState, type FormEvent } from 'react'

import { useApi, useAuth } from '../auth/AuthContext'
import { IconPlus } from '../components/icons'
import { ErrorAlert, Modal, Spinner } from '../components/ui'
import type { Role, User } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Viewer — can read published guides',
  author: 'Author — can write and publish guides',
  admin: 'Admin — can also manage people and categories',
}

function NewUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const api = useApi()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<Role>('author')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)

    try {
      await api.createUser({ email: email.trim(), displayName: displayName.trim(), role, password })
      onCreated()
      onClose()
    } catch (cause) {
      setError(cause)
      setSubmitting(false)
    }
  }

  return (
    <Modal title="Add a person" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={error} />

        <div className="field">
          <label className="field__label" htmlFor="user-name">
            Full name
          </label>
          <input
            id="user-name"
            className="input"
            required
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="user-email">
            Email
          </label>
          <input
            id="user-email"
            className="input"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field__label" htmlFor="user-role">
            Role
          </label>
          <select
            id="user-role"
            className="select"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
          >
            {(Object.keys(ROLE_LABELS) as Role[]).map((value) => (
              <option key={value} value={value}>
                {ROLE_LABELS[value]}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="user-password">
            Initial password
          </label>
          <input
            id="user-password"
            className="input"
            type="text"
            required
            minLength={12}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <span className="field__hint">
            At least 12 characters. Send it to them over a channel other than email, and ask them to
            change it after signing in.
          </span>
        </div>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={submitting}>
            {submitting ? 'Adding…' : 'Add person'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

/**
 * Renaming somebody, in place.
 *
 * People at a facility change name — after a marriage, or because the account
 * was created from an email address and reads as "t.dehoog" on every guide they
 * have ever written. The alternative to renaming is a second account, which
 * splits one person's authorship in two.
 */
function NameCell({ person, onRenamed }: { person: User; onRenamed: () => void }) {
  const api = useApi()
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(person.displayName)
  const [saving, setSaving] = useState(false)

  async function save() {
    const displayName = value.trim()
    if (displayName === '' || displayName === person.displayName) {
      setEditing(false)
      setValue(person.displayName)
      return
    }
    setSaving(true)
    try {
      await api.updateUser(person.id, { displayName })
      onRenamed()
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  if (!editing) {
    return (
      <button
        className="button button--ghost button--sm"
        type="button"
        aria-label={`Rename ${person.displayName}`}
        onClick={() => setEditing(true)}
      >
        {person.displayName}
      </button>
    )
  }

  return (
    <div className="field-pair">
      <input
        className="input"
        aria-label={`Name for ${person.email}`}
        value={value}
        disabled={saving}
        autoFocus
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') void save()
          if (event.key === 'Escape') {
            setValue(person.displayName)
            setEditing(false)
          }
        }}
      />
      <button className="button button--sm" type="button" disabled={saving} onClick={() => void save()}>
        Save
      </button>
    </div>
  )
}

export function UsersPage() {
  const api = useApi()
  const { user: currentUser } = useAuth()
  const { data, error, loading, reload } = useAsync(() => api.listUsers(), [api])
  const [adding, setAdding] = useState(false)
  const [changeError, setChangeError] = useState<unknown>(null)

  async function change(id: string, changes: { role?: Role; isActive?: boolean }) {
    setChangeError(null)
    try {
      await api.updateUser(id, changes)
      reload()
    } catch (cause) {
      setChangeError(cause)
    }
  }

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>People</h1>
          <p className="page-header__sub">Everyone with access to Reticle.</p>
        </div>
        <div className="page-actions">
          <button className="button button--primary" type="button" onClick={() => setAdding(true)}>
            <IconPlus />
            Add person
          </button>
        </div>
      </div>

      <ErrorAlert error={changeError} />

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Added</th>
              <th>Access</th>
            </tr>
          </thead>
          <tbody>
            {(data ?? []).map((person) => (
              <tr key={person.id} className={person.isActive ? undefined : 'user-row--inactive'}>
                <td data-label="Name">
                  <NameCell person={person} onRenamed={reload} />
                </td>
                <td data-label="Email">{person.email}</td>
                <td data-label="Role">
                  <select
                    className="select"
                    style={{ maxWidth: '9rem' }}
                    aria-label={`Role for ${person.displayName}`}
                    value={person.role}
                    disabled={person.id === currentUser?.id}
                    title={
                      person.id === currentUser?.id
                        ? 'You cannot change your own role — ask another admin.'
                        : undefined
                    }
                    onChange={(event) => void change(person.id, { role: event.target.value as Role })}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="author">Author</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td data-label="Added">{new Date(person.createdAt).toLocaleDateString()}</td>
                <td data-label="Access">
                  {/* Deactivating rather than deleting: their name stays on the
                      guides they wrote, and the audit trail stays readable. */}
                  <button
                    className={`button button--sm${person.isActive ? '' : ' button--primary'}`}
                    type="button"
                    disabled={person.id === currentUser?.id}
                    title={
                      person.id === currentUser?.id
                        ? 'You cannot switch off your own account.'
                        : undefined
                    }
                    onClick={() => void change(person.id, { isActive: !person.isActive })}
                  >
                    {person.isActive ? 'Deactivate' : 'Reactivate'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {adding && <NewUserDialog onClose={() => setAdding(false)} onCreated={reload} />}
    </>
  )
}

import { useSuspenseQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { useApi } from '../api/context'
import { useSession } from '../auth/session'
import { IconPlus } from '../components/icons'
import { ErrorAlert, Modal } from '../components/ui'
import type { Role } from '../domain/types'
import { useCreateUser, useUpdateUser, userQueries } from '../queries/users'

const ROLE_LABELS: Record<Role, string> = {
  viewer: 'Viewer — can read published guides',
  author: 'Author — can write and publish guides',
  admin: 'Admin — can also manage people and categories',
}

function NewUserDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateUser()
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState<Role>('author')
  const [password, setPassword] = useState('')

  function onSubmit(event: FormEvent) {
    event.preventDefault()
    create.mutate(
      { email: email.trim(), displayName: displayName.trim(), role, password },
      { onSuccess: onClose },
    )
  }

  return (
    <Modal title="Add a person" onClose={onClose}>
      <form onSubmit={onSubmit}>
        <ErrorAlert error={create.error} />

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
          <button className="button button--primary" type="submit" disabled={create.isPending}>
            {create.isPending ? 'Adding…' : 'Add person'}
          </button>
          <button className="button" type="button" onClick={onClose}>
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  )
}

export function UsersPage() {
  const api = useApi()
  const { user: currentUser } = useSession()
  const { data: people } = useSuspenseQuery(userQueries.list(api))
  const update = useUpdateUser()
  const [adding, setAdding] = useState(false)

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

      <ErrorAlert error={update.error} />

      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
            </tr>
          </thead>
          <tbody>
            {people.map((person) => (
              <tr key={person.id}>
                <td>{person.displayName}</td>
                <td>{person.email}</td>
                <td>
                  <select
                    className="select"
                    style={{ maxWidth: '9rem' }}
                    value={person.role}
                    disabled={person.id === currentUser?.id}
                    title={
                      person.id === currentUser?.id
                        ? 'You cannot change your own role — ask another admin.'
                        : undefined
                    }
                    onChange={(event) =>
                      update.mutate({ id: person.id, changes: { role: event.target.value as Role } })
                    }
                  >
                    <option value="viewer">Viewer</option>
                    <option value="author">Author</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {adding && <NewUserDialog onClose={() => setAdding(false)} />}
    </>
  )
}

/**
 * The front page's own banner: whose installation this is.
 *
 * The same three fields as a section — a title, a paragraph, a picture — and
 * deliberately the same form, because they are the same job at the level above.
 * A facility that can arrange its sections and not say its own name would be an
 * odd thing to hand somebody.
 *
 * These used to be `RETICLE_ORGANISATION_*`, read from the environment at
 * start-up. That is the right home for a secret and the wrong one for a front
 * page: changing the tagline meant editing a file on the server and restarting
 * the process, and the person who knows what the tagline should say is not the
 * person with a shell on the box. The variables are still read — they are what
 * a fresh installation starts with, written into the row the first time
 * anything asks for it.
 *
 * There is no delete. A facility is the thing the site is, not something in it.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { Thumbnail } from '../components/Thumbnail'
import { ErrorAlert, Spinner } from '../components/ui'
import type { Facility } from '../domain/types'
import { useAsync } from '../hooks/useAsync'

export function FacilityFormPage() {
  const api = useApi()
  const { data, error, loading } = useAsync(() => api.getFacility(), [api])

  if (loading) return <Spinner />
  if (error) return <ErrorAlert error={error} />
  if (!data) return null

  return <FacilityForm facility={data} />
}

function FacilityForm({ facility }: { facility: Facility }) {
  const api = useApi()
  const navigate = useNavigate()
  const { refresh } = useAuth()

  const [name, setName] = useState(facility.name)
  const [tagline, setTagline] = useState(facility.tagline)
  const [mediaId, setMediaId] = useState<string | null>(facility.heroMediaId)
  const [pictureUrl, setPictureUrl] = useState<string | null>(facility.heroImageUrl)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)

  async function onPickPicture(file: File | null) {
    if (!file) return
    setUploading(true)
    setFailure(null)
    try {
      const media = await api.uploadMedia(file)
      setMediaId(media.id)
      setPictureUrl(media.url)
    } catch (cause) {
      setFailure(cause)
    } finally {
      setUploading(false)
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setFailure(null)
    try {
      await api.updateFacility({
        name: name.trim(),
        tagline: tagline.trim(),
        heroMediaId: mediaId,
      })
      /* The name and the picture are in the rail and the browser tab as well as
         on the banner, and they were fetched once when the app started. Without
         this the front page is right and everything around it is still saying
         the old name. */
      await refresh()
      navigate('/')
    } catch (cause) {
      setFailure(cause)
      setSaving(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div className="page-header__text">
          <h1>Edit the front page</h1>
        </div>
      </div>

      <form className="section-form" onSubmit={onSubmit}>
        <ErrorAlert error={failure} />

        <div className="field">
          <label className="field__label" htmlFor="facility-name">
            Title
          </label>
          <input
            id="facility-name"
            className="input"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <span className="field__hint">
            The facility's name, across the top of the front page and beside the mark in the rail.
          </span>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="facility-tagline">
            Text
          </label>
          <textarea
            id="facility-tagline"
            className="input"
            rows={4}
            value={tagline}
            placeholder="Two or three sentences, shown under the name on the front page."
            onChange={(event) => setTagline(event.target.value)}
          />
        </div>

        <div className="field">
          <span className="field__label">Picture</span>
          <div className="hero-picker">
            <Thumbnail seed={name || 'Facility'} src={pictureUrl} className="hero-picker__preview" />
            <div className="hero-picker__controls">
              <input
                type="file"
                accept="image/*"
                onChange={(event) => void onPickPicture(event.target.files?.[0] ?? null)}
              />
              {pictureUrl && (
                <button
                  className="button"
                  type="button"
                  onClick={() => {
                    setMediaId(null)
                    setPictureUrl(null)
                  }}
                >
                  Remove
                </button>
              )}
              {uploading && <span className="save-state">Uploading…</span>}
            </div>
          </div>
        </div>

        <div className="page-actions">
          <button className="button button--primary" type="submit" disabled={saving || uploading}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
          <button className="button" type="button" onClick={() => navigate('/')}>
            Cancel
          </button>
        </div>
      </form>
    </>
  )
}

import { getRouteApi } from '@tanstack/react-router'

import { GuideEditor } from '../components/editor/GuideEditor'

const route = getRouteApi('/g/$id/edit')

/**
 * The route's loader has already fetched the guide, fresh, by the time this
 * renders. Keying the editor on the guide's id means moving from one guide to
 * another starts a new working copy instead of carrying the old one over.
 */
export function GuideEditorPage() {
  const guide = route.useLoaderData()
  return <GuideEditor key={guide.id} initial={guide} />
}

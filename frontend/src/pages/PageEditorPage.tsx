import { getRouteApi } from '@tanstack/react-router'

import { PageEditor } from '../components/editor/PageEditor'

const route = getRouteApi('/w/$id/edit')

/** See `GuideEditorPage`: the loader supplies the page, the key resets per page. */
export function PageEditorPage() {
  const page = route.useLoaderData()
  return <PageEditor key={page.id} initial={page} />
}

import { useMutation } from '@tanstack/react-query'

import { useApi } from '../api/context'

/**
 * Uploads touch no cached read: a new image is not listed anywhere until the
 * guide or page that uses it is saved, and that save does the invalidating.
 */
export function useUploadMedia() {
  const api = useApi()
  return useMutation({
    mutationFn: (file: File) => api.uploadMedia(file),
  })
}

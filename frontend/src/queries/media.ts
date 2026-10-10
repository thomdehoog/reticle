import { useMutation } from '@tanstack/react-query'

import type { UploadOptions } from '../api/client'
import { useApi } from '../api/context'

export interface UploadRequest extends UploadOptions {
  file: File
}

/**
 * Uploads touch no cached read: a new image is not listed anywhere until the
 * guide or page that uses it is saved, and that save does the invalidating.
 */
export function useUploadMedia() {
  const api = useApi()
  return useMutation({
    mutationFn: ({ file, ...options }: UploadRequest) => api.uploadMedia(file, options),
  })
}

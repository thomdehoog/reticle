import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'

import { useApi } from '../api/context'
import type { NewUserInput, ReticleApi } from '../api/reticle'
import type { Role } from '../domain/types'

export const userKeys = {
  all: ['users'] as const,
  list: () => [...userKeys.all, 'list'] as const,
}

export const userQueries = {
  list: (api: ReticleApi) =>
    queryOptions({
      queryKey: userKeys.list(),
      queryFn: () => api.listUsers(),
    }),
}

export function useCreateUser() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: NewUserInput) => api.createUser(input),
    /* The initial password is in the variables; see `useLogin`. */
    gcTime: 0,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: userKeys.all }),
  })
}

export function useUpdateUser() {
  const api = useApi()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      changes,
    }: {
      id: string
      changes: { displayName?: string; role?: Role; isActive?: boolean }
    }) => api.updateUser(id, changes),
    /* Settled, not success: after a refused role change the select must snap
       back to what the server still holds. */
    onSettled: () => queryClient.invalidateQueries({ queryKey: userKeys.all }),
  })
}

export function useChangePassword() {
  const api = useApi()
  return useMutation({
    mutationFn: ({
      userId,
      currentPassword,
      newPassword,
    }: {
      userId: string
      currentPassword: string
      newPassword: string
    }) => api.changePassword(userId, currentPassword, newPassword),
    gcTime: 0,
  })
}

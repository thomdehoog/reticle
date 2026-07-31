/**
 * Typed façade over the endpoints in docs/API.md.
 *
 * Components call these methods and never build URLs themselves, so a contract
 * change lands in one file rather than being scattered across the UI.
 */

import type {
  Category,
  Guide,
  GuideStatus,
  GuideSummary,
  Media,
  Role,
  User,
} from '../domain/types'
import type { ApiClient } from './client'

/**
 * A type alias rather than an interface: TypeScript only gives aliases an
 * implicit index signature, which is what lets `queryString` accept this
 * without each caller widening it by hand.
 */
export type GuideQuery = {
  categoryId?: string
  status?: GuideStatus
  q?: string
  authorId?: string
}

export interface GuideRevisionSummary {
  version: number
  publishedAt: string
  publishedBy: { id: string; displayName: string }
}

function queryString(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, value)
  }
  const rendered = search.toString()
  return rendered === '' ? '' : `?${rendered}`
}

export class ReticleApi {
  constructor(private readonly http: ApiClient) {}

  login(email: string, password: string): Promise<User> {
    return this.http.post<User>('/auth/login', { email, password })
  }

  logout(): Promise<void> {
    return this.http.post<void>('/auth/logout')
  }

  me(): Promise<User> {
    return this.http.get<User>('/auth/me')
  }

  listCategories(): Promise<Category[]> {
    return this.http.get<Category[]>('/categories')
  }

  createCategory(input: { name: string; description?: string; parentId?: string | null }): Promise<Category> {
    return this.http.post<Category>('/categories', input)
  }

  updateCategory(id: string, changes: Partial<Pick<Category, 'name' | 'description' | 'parentId' | 'orderIndex'>>): Promise<Category> {
    return this.http.patch<Category>(`/categories/${id}`, changes)
  }

  deleteCategory(id: string): Promise<void> {
    return this.http.delete<void>(`/categories/${id}`)
  }

  listGuides(query: GuideQuery = {}): Promise<GuideSummary[]> {
    return this.http.get<GuideSummary[]>(`/guides${queryString(query)}`)
  }

  getGuide(idOrSlug: string): Promise<Guide> {
    return this.http.get<Guide>(`/guides/${encodeURIComponent(idOrSlug)}`)
  }

  createGuide(title: string, categoryId: string): Promise<Guide> {
    return this.http.post<Guide>('/guides', { title, categoryId })
  }

  /**
   * Saves the whole document. `expectedUpdatedAt` is what the editor last saw;
   * the server rejects the write with `conflict` if someone else saved in the
   * meantime, which is what stops two ZMB staff silently overwriting each other.
   */
  saveGuide(guide: Guide): Promise<Guide> {
    return this.http.put<Guide>(`/guides/${guide.id}`, {
      ...guide,
      expectedUpdatedAt: guide.updatedAt,
    })
  }

  publishGuide(id: string): Promise<Guide> {
    return this.http.post<Guide>(`/guides/${id}/publish`)
  }

  unpublishGuide(id: string): Promise<Guide> {
    return this.http.post<Guide>(`/guides/${id}/unpublish`)
  }

  archiveGuide(id: string): Promise<void> {
    return this.http.delete<void>(`/guides/${id}`)
  }

  listRevisions(id: string): Promise<GuideRevisionSummary[]> {
    return this.http.get<GuideRevisionSummary[]>(`/guides/${id}/revisions`)
  }

  getRevision(id: string, version: number): Promise<Guide> {
    return this.http.get<Guide>(`/guides/${id}/revisions/${version}`)
  }

  uploadMedia(file: File): Promise<Media> {
    return this.http.upload<Media>('/media', file)
  }

  listUsers(): Promise<User[]> {
    return this.http.get<User[]>('/users')
  }

  createUser(input: { email: string; displayName: string; role: Role; password: string }): Promise<User> {
    return this.http.post<User>('/users', input)
  }

  updateUser(id: string, changes: { displayName?: string; role?: Role; isActive?: boolean }): Promise<User> {
    return this.http.patch<User>(`/users/${id}`, changes)
  }

  changePassword(id: string, currentPassword: string, newPassword: string): Promise<void> {
    return this.http.post<void>(`/users/${id}/password`, { currentPassword, newPassword })
  }
}

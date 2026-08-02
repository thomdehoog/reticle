/**
 * Typed façade over the endpoints in docs/API.md.
 *
 * Components call these methods and never build URLs themselves, so a contract
 * change lands in one file rather than being scattered across the UI.
 */

import type {
  AppConfig,
  Category,
  ContentStatus,
  Guide,
  GuideSummary,
  Media,
  Page,
  PageSummary,
  Role,
  SearchResult,
  Tag,
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
  status?: ContentStatus
  q?: string
  authorId?: string
  /** Comma-separated tag slugs; a guide must carry all of them to match. */
  tags?: string
  /** Only the guides an author has marked as quick links. */
  quickLink?: boolean
}

export type PageQuery = {
  categoryId?: string
  status?: ContentStatus
  q?: string
}

export interface RevisionSummary {
  version: number
  publishedAt: string
  publishedBy: { id: string; displayName: string }
}

/* A flag is sent as it was given — `?quickLink=false` asks for the guides that
   are not quick links, which is not the same question as not asking. Only an
   absent value drops out, so an unfiltered listing keeps the URL it always had. */
function queryString(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const rendered = search.toString()
  return rendered === '' ? '' : `?${rendered}`
}

export class ReticleApi {
  constructor(private readonly http: ApiClient) {}

  /**
   * Whose instance this is. Fetched before anyone signs in, because the login
   * screen has to say which facility it belongs to — one Reticle per facility
   * is the intended shape, and they differ only in whose name is on them.
   */
  configuration(): Promise<AppConfig> {
    return this.http.get<AppConfig>('/config')
  }

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

  createCategory(input: {
    name: string
    description?: string
    parentId?: string | null
    isHidden?: boolean
    heroMediaId?: string | null
  }): Promise<Category> {
    return this.http.post<Category>('/categories', input)
  }

  updateCategory(
    id: string,
    changes: Partial<
      Pick<
        Category,
        'name' | 'description' | 'parentId' | 'orderIndex' | 'isHidden' | 'heroMediaId'
      >
    >,
  ): Promise<Category> {
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

  listGuideRevisions(id: string): Promise<RevisionSummary[]> {
    return this.http.get<RevisionSummary[]>(`/guides/${id}/revisions`)
  }

  getGuideRevision(id: string, version: number): Promise<Guide> {
    return this.http.get<Guide>(`/guides/${id}/revisions/${version}`)
  }

  listPages(query: PageQuery = {}): Promise<PageSummary[]> {
    return this.http.get<PageSummary[]>(`/pages${queryString(query)}`)
  }

  getPage(idOrSlug: string): Promise<Page> {
    return this.http.get<Page>(`/pages/${encodeURIComponent(idOrSlug)}`)
  }

  /** The landing page for a category, or null when it has not been written yet. */
  getCategoryLandingPage(categoryId: string): Promise<Page | null> {
    return this.http.get<Page | null>(`/categories/${categoryId}/page`)
  }

  createPage(input: {
    title: string
    categoryId?: string | null
    isLanding?: boolean
  }): Promise<Page> {
    return this.http.post<Page>('/pages', input)
  }

  savePage(page: Page): Promise<Page> {
    return this.http.put<Page>(`/pages/${page.id}`, {
      ...page,
      expectedUpdatedAt: page.updatedAt,
    })
  }

  publishPage(id: string): Promise<Page> {
    return this.http.post<Page>(`/pages/${id}/publish`)
  }

  unpublishPage(id: string): Promise<Page> {
    return this.http.post<Page>(`/pages/${id}/unpublish`)
  }

  /** Archives rather than deletes, despite the verb; the server keeps the rows. */
  archivePage(id: string): Promise<void> {
    return this.http.delete<void>(`/pages/${id}`)
  }

  listPageRevisions(id: string): Promise<RevisionSummary[]> {
    return this.http.get<RevisionSummary[]>(`/pages/${id}/revisions`)
  }

  getPageRevision(id: string, version: number): Promise<Page> {
    return this.http.get<Page>(`/pages/${id}/revisions/${version}`)
  }

  /** Every tag in use, with counts, for the tag picker and guide-list embeds. */
  listTags(): Promise<Tag[]> {
    return this.http.get<Tag[]>('/tags')
  }

  search(term: string): Promise<SearchResult[]> {
    return this.http.get<SearchResult[]>(`/search${queryString({ q: term })}`)
  }

  uploadMedia(file: File): Promise<Media> {
    return this.http.upload<Media>('/media', file)
  }

  listUsers(): Promise<User[]> {
    return this.http.get<User[]>('/users')
  }

  createUser(input: {
    email: string
    displayName: string
    role: Role
    password: string
  }): Promise<User> {
    return this.http.post<User>('/users', input)
  }

  updateUser(
    id: string,
    changes: { displayName?: string; role?: Role; isActive?: boolean },
  ): Promise<User> {
    return this.http.patch<User>(`/users/${id}`, changes)
  }

  changePassword(id: string, currentPassword: string, newPassword: string): Promise<void> {
    return this.http.post<void>(`/users/${id}/password`, { currentPassword, newPassword })
  }
}

/**
 * Typed façade over the endpoints in docs/API.md.
 *
 * Components call these methods and never build URLs themselves, so a contract
 * change lands in one file rather than being scattered across the UI.
 */

import type {
  Category,
  ContentStatus,
  ContentView,
  Guide,
  GuideSummary,
  Media,
  Page,
  PageSummary,
  Role,
  SearchResult,
  Tag,
  User,
  UserRef,
} from '../domain/types'
import { uploadLimitsFrom, type UploadLimits } from '../domain/media'
import type { ApiClient, UploadOptions } from './client'

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
}

export type PageQuery = {
  categoryId?: string
  status?: ContentStatus
  q?: string
}

export interface RevisionSummary {
  version: number
  publishedAt: string
  publishedBy: UserRef
}

export interface CategoryInput {
  name: string
  description?: string
  parentId?: string | null
  isHidden?: boolean
}

export type CategoryChanges = Partial<
  Pick<Category, 'name' | 'description' | 'parentId' | 'orderIndex' | 'isHidden'>
>

export interface NewUserInput {
  email: string
  displayName: string
  role: Role
  password: string
}

export interface NewPageInput {
  title: string
  categoryId?: string | null
  isLanding?: boolean
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

  createCategory(input: CategoryInput): Promise<Category> {
    return this.http.post<Category>('/categories', input)
  }

  updateCategory(id: string, changes: CategoryChanges): Promise<Category> {
    return this.http.patch<Category>(`/categories/${id}`, changes)
  }

  deleteCategory(id: string): Promise<void> {
    return this.http.delete<void>(`/categories/${id}`)
  }

  listGuides(query: GuideQuery = {}): Promise<GuideSummary[]> {
    return this.http.get<GuideSummary[]>(`/guides${queryString(query)}`)
  }

  /**
   * One guide. A viewer always receives the published snapshot. An author
   * receives the working copy — what the editor needs — unless `view` is
   * `'published'`, which is exactly what a viewer would get and is `not_found`
   * for a guide that is not published at the moment.
   */
  getGuide(idOrSlug: string, view?: ContentView): Promise<Guide> {
    return this.http.get<Guide>(`/guides/${encodeURIComponent(idOrSlug)}${queryString({ view })}`)
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

  /**
   * Discards unpublished changes: the working copy becomes the published
   * version again. Resolves to that working copy.
   */
  revertGuide(id: string): Promise<Guide> {
    return this.http.post<Guide>(`/guides/${id}/revert`)
  }

  archiveGuide(id: string): Promise<void> {
    return this.http.delete<void>(`/guides/${id}`)
  }

  /**
   * Counts one read. A separate call rather than a side effect of `getGuide`,
   * so opening a guide in the editor does not inflate its own view count.
   */
  recordGuideView(id: string): Promise<void> {
    return this.http.post<void>(`/guides/${id}/view`)
  }

  /**
   * The guide as a PDF file.
   *
   * A request, not a link: the export is rationed, and a busy server answers
   * `rate_limited` with how long to wait. Followed as a plain link, that answer
   * would have been saved to disk as "guide.pdf".
   */
  downloadGuidePdf(idOrSlug: string, view?: ContentView): Promise<Blob> {
    return this.http.download(
      `/guides/${encodeURIComponent(idOrSlug)}/pdf${queryString({ view })}`,
    )
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

  /** One page; `view` as for `getGuide`. */
  getPage(idOrSlug: string, view?: ContentView): Promise<Page> {
    return this.http.get<Page>(`/pages/${encodeURIComponent(idOrSlug)}${queryString({ view })}`)
  }

  /**
   * The landing page for a category, or null when there is none this user may
   * see — the server answers 200 with a JSON `null`, not 404, so "no landing
   * page" is an ordinary result rather than an error to catch.
   */
  getCategoryLandingPage(categoryId: string, view?: ContentView): Promise<Page | null> {
    return this.http.get<Page | null>(`/categories/${categoryId}/page${queryString({ view })}`)
  }

  createPage(input: NewPageInput): Promise<Page> {
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

  revertPage(id: string): Promise<Page> {
    return this.http.post<Page>(`/pages/${id}/revert`)
  }

  archivePage(id: string): Promise<void> {
    return this.http.delete<void>(`/pages/${id}`)
  }

  recordPageView(id: string): Promise<void> {
    return this.http.post<void>(`/pages/${id}/view`)
  }

  listPageRevisions(id: string): Promise<RevisionSummary[]> {
    return this.http.get<RevisionSummary[]>(`/pages/${id}/revisions`)
  }

  getPageRevision(id: string, version: number): Promise<Page> {
    return this.http.get<Page>(`/pages/${id}/revisions/${version}`)
  }

  /**
   * The limits this server enforces. Normalised on the way in, so that nothing
   * downstream has to wonder whether a figure it compares a file size against
   * is really a number.
   */
  async getUploadLimits(): Promise<UploadLimits> {
    return uploadLimitsFrom(await this.http.get<unknown>('/config'))
  }

  /** Every tag in use, with counts, for the tag picker and guide-list embeds. */
  listTags(): Promise<Tag[]> {
    return this.http.get<Tag[]>('/tags')
  }

  search(term: string): Promise<SearchResult[]> {
    return this.http.get<SearchResult[]>(`/search${queryString({ q: term })}`)
  }

  /** One image or video; the server decides which from the bytes, not the name. */
  uploadMedia(file: File, options?: UploadOptions): Promise<Media> {
    return this.http.upload<Media>('/media', file, options)
  }

  /** Where the browser fetches a media item's bytes, for an `<img>` built from an id. */
  mediaUrl(id: string): string {
    return this.http.url(`/media/${encodeURIComponent(id)}`)
  }

  /** The copy of an image meant for showing; see `Media.displayUrl`. */
  mediaDisplayUrl(id: string): string {
    return `${this.mediaUrl(id)}?size=display`
  }

  listUsers(): Promise<User[]> {
    return this.http.get<User[]>('/users')
  }

  createUser(input: NewUserInput): Promise<User> {
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

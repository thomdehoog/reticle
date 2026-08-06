/**
 * The categories, and the rules about which of them anybody sees.
 *
 * The API returns one flat list; almost every screen wants something else from
 * it. `buildCategoryTree` turns it into the nesting the front page and the
 * admin screen browse. `browsableCategories` drops the ones a reader should not
 * be sent to: the holding categories, and the ones with nothing published under
 * them. `useBrowsableCategories` fetches what that rule is measured against and
 * applies it, which is what the rail and the phone drawer list.
 * `useCategories` fetches the list itself, unfiltered, because the editors and
 * the admin screen need the hidden and the empty ones too.
 *
 * It all lives together because the hiding rule is the fragile part: it must be
 * applied on the browse surfaces and nowhere else, and a copy of it made on one
 * screen is how a category quietly stops being editable.
 */

import { useApi, useAuth } from '../auth/AuthContext'
import type { Category } from '../domain/types'
import { useAsync } from './useAsync'

export interface CategoryNode extends Category {
  children: CategoryNode[]
}

/**
 * Builds the category tree from the flat list the API returns.
 *
 * A category whose parent is missing (deleted, or not visible to this user) is
 * promoted to the top level rather than vanishing — losing guides silently is
 * far worse than showing a category slightly out of place.
 */
export function buildCategoryTree(categories: Category[]): CategoryNode[] {
  const byId = new Map<string, CategoryNode>()
  for (const category of categories) byId.set(category.id, { ...category, children: [] })

  const roots: CategoryNode[] = []
  for (const node of byId.values()) {
    const parent = node.parentId ? byId.get(node.parentId) : undefined
    if (parent) parent.children.push(node)
    else roots.push(node)
  }

  const sortRecursively = (nodes: CategoryNode[]) => {
    nodes.sort((a, b) => a.orderIndex - b.orderIndex || a.name.localeCompare(b.name))
    for (const node of nodes) sortRecursively(node.children)
  }
  sortRecursively(roots)

  return roots
}

/**
 * How much published material a category holds, counting everything nested
 * under it.
 *
 * A parent's total has to include its children's, hidden children included:
 * those documents really are reachable from the parent, through the sub-
 * categories underneath it and through the tag-gathered lists on its own
 * landing page.
 *
 * Counting from one listing rather than asking per category is what keeps a
 * page with five sub-sections to one request instead of six.
 */
export function countDocumentsByCategory(
  categories: Category[],
  documents: { categoryId: string | null }[],
): (categoryId: string) => number {
  const direct = new Map<string, number>()
  for (const document of documents) {
    if (document.categoryId === null) continue
    direct.set(document.categoryId, (direct.get(document.categoryId) ?? 0) + 1)
  }

  const childrenOf = new Map<string, Category[]>()
  for (const category of categories) {
    if (!category.parentId) continue
    const siblings = childrenOf.get(category.parentId) ?? []
    siblings.push(category)
    childrenOf.set(category.parentId, siblings)
  }

  const total = (categoryId: string): number =>
    (direct.get(categoryId) ?? 0) +
    (childrenOf.get(categoryId) ?? []).reduce((sum, child) => sum + total(child.id), 0)

  return total
}

/**
 * The categories a reader may browse through.
 *
 * Two kinds are dropped. Holding categories exist to own guides that are
 * reached by tag, and listing them turns the front page into a list of
 * filing-cabinet drawers rather than of subjects. Empty ones lead nowhere: a
 * category with nothing published under it opens on a heading and an apology,
 * and a wall of equally confident tiles gives a reader no way to tell which of
 * them that will be.
 *
 * A published page of the category's own counts as much as a guide does. ZMB's
 * category pages are prose with tag-gathered lists in them, and the guides
 * those lists surface need not sit under the category at all — Light
 * Microscopy's page fills itself from the confocal holding pen, which stands
 * beside it rather than under it. Counting guides alone would hide the most
 * written-on page on the site as though it were a dead end.
 *
 * Neither kind is secret, and this is not a permission: the URL works, the
 * guides stay published, search and tags find them, and the admin screen and
 * both editors' pickers list every category there is. The first published guide
 * brings the category back.
 *
 * **An administrator keeps the empty ones.** That is a change of mind, and the
 * reasoning it replaces was good: one tree that everybody sees the same way,
 * rather than a private one in which an author cannot tell what a reader is
 * being offered. It held while categories only ever arrived from the seeder or
 * from the migration, already full. Now that one can be made from the front
 * page, the first thing that happens after making it is that it disappears —
 * no tile on the section it was added to, and a rail that cannot say where you
 * are, because the section you are standing in is not in the list the path is
 * built from. A control whose result vanishes is worse than a tree with two
 * views of it.
 *
 * So the divergence is admitted rather than hidden: an empty section is drawn
 * for an administrator wearing a mark that says a reader cannot see it yet.
 * Hidden categories stay hidden for everyone — those are deliberate, there are
 * a dozen of them, and they are reached by tag on purpose.
 */
export function browsableCategories(
  categories: Category[],
  publishedGuides: { categoryId: string }[],
  publishedPages: { categoryId: string | null }[],
  { keepEmpty = false }: { keepEmpty?: boolean } = {},
): Category[] {
  const held = countDocumentsByCategory(categories, [...publishedGuides, ...publishedPages])
  return categories.filter(
    (category) => !category.isHidden && (keepEmpty || held(category.id) > 0),
  )
}

/** Whether a reader would be shown this section, given what is published. */
export function isEmptyToReaders(
  category: Category,
  categories: Category[],
  publishedGuides: { categoryId: string }[],
  publishedPages: { categoryId: string | null }[],
): boolean {
  const held = countDocumentsByCategory(categories, [...publishedGuides, ...publishedPages])
  return held(category.id) === 0
}

/**
 * The categories to browse, with that rule already applied.
 *
 * The two listings it is measured against are fetched here so that no screen
 * has to know which ones they are. A screen that asked for the wrong listing —
 * every guide rather than the published ones — would hide nothing at all, and
 * nobody would notice for months.
 */
export function useBrowsableCategories() {
  const api = useApi()
  const { can } = useAuth()
  const keepEmpty = can('admin')
  return useAsync(async () => {
    const [categories, guides, pages] = await Promise.all([
      api.listCategories(),
      api.listGuides({ status: 'published' }),
      api.listPages({ status: 'published' }),
    ])
    return browsableCategories(categories, guides, pages, { keepEmpty })
  }, [api, keepEmpty])
}

/**
 * Every category, hidden and empty ones included.
 *
 * This is what the admin screen and the editors need: an author moving a guide
 * into a holding category has to be able to pick it, an author filling an empty
 * category has to be able to choose it, and an administrator who cannot see a
 * hidden category cannot un-hide it.
 */
export function useCategories() {
  const api = useApi()
  return useAsync(() => api.listCategories(), [api])
}

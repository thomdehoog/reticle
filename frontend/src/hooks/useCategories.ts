import { useApi } from '../auth/AuthContext'
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
 * The categories a reader may browse through.
 *
 * Holding categories are hidden from the tree on purpose: they exist to own
 * guides that are reached by tag, and listing them turns the front page into a
 * list of filing-cabinet drawers rather than of subjects. They are not secret —
 * their URL works, their guides are published, and search finds them — so this
 * filters the browse surfaces only.
 */
export function browsableCategories(categories: Category[]): Category[] {
  return categories.filter((category) => !category.isHidden)
}

/**
 * Every category, hidden ones included.
 *
 * This is what the admin screen and the editors need: an author moving a guide
 * into a holding category has to be able to pick it, and an administrator who
 * cannot see a hidden category cannot un-hide it.
 */
export function useCategories() {
  const api = useApi()
  return useAsync(() => api.listCategories(), [api])
}

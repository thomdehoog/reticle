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

export function useCategories() {
  const api = useApi()
  return useAsync(() => api.listCategories(), [api])
}

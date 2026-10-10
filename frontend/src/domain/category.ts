import type { Category } from './types'

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
    nodes.sort(byOrder)
    for (const node of nodes) sortRecursively(node.children)
  }
  sortRecursively(roots)

  return roots
}

export function byOrder(a: Category, b: Category): number {
  return a.orderIndex - b.orderIndex || a.name.localeCompare(b.name)
}

/**
 * The tree people browse: everything except holding categories.
 *
 * A holding category exists to own guides that are reached through tags, so it
 * is left out of navigation — but only out of navigation. It is still in the
 * list this is built from, which is why its URL, its breadcrumbs and the
 * editor's category picker all keep working. A visible category filed under a
 * hidden one is promoted by the same rule as any other orphan.
 */
export function buildBrowsableTree(categories: Category[]): CategoryNode[] {
  return buildCategoryTree(categories.filter((category) => !category.isHidden))
}

/** The visible categories directly under one, in display order. */
export function browsableChildren(categories: Category[], parentId: string): Category[] {
  return categories
    .filter((category) => category.parentId === parentId && !category.isHidden)
    .sort(byOrder)
}

/** A node and everything beneath it, as ids — for totals that include sub-categories. */
export function subtreeIds(node: CategoryNode): string[] {
  return [node.id, ...node.children.flatMap(subtreeIds)]
}

/**
 * The categories one could be moved under without making a loop: anything that
 * is not itself and not already beneath it.
 */
export function possibleParents(categories: Category[], categoryId: string | null): Category[] {
  if (categoryId === null) return [...categories].sort(byOrder)

  const excluded = new Set<string>([categoryId])
  let grew = true
  while (grew) {
    grew = false
    for (const category of categories) {
      if (category.parentId && excluded.has(category.parentId) && !excluded.has(category.id)) {
        excluded.add(category.id)
        grew = true
      }
    }
  }
  return categories.filter((category) => !excluded.has(category.id)).sort(byOrder)
}

import { describe, expect, it } from 'vitest'

import {
  ancestorsOf,
  browsableChildren,
  buildBrowsableTree,
  buildCategoryTree,
  byOrder,
  moveAmongSiblings,
  possibleParents,
  subtreeIds,
} from './category'
import type { Category } from './types'

function category(id: string, overrides: Partial<Category> = {}): Category {
  return {
    id,
    slug: id,
    name: id,
    description: '',
    parentId: null,
    orderIndex: 0,
    isHidden: false,
    ...overrides,
  }
}

const names = (nodes: { name: string }[]) => nodes.map((node) => node.name)

describe('buildCategoryTree', () => {
  it('nests children under their parent, in order then by name', () => {
    const tree = buildCategoryTree([
      category('light', { orderIndex: 2 }),
      category('electron', { orderIndex: 1 }),
      category('widefield', { parentId: 'light', orderIndex: 1 }),
      category('confocal', { parentId: 'light', orderIndex: 1 }),
      category('sted', { parentId: 'light', orderIndex: 0 }),
    ])

    expect(names(tree)).toEqual(['electron', 'light'])
    expect(names(tree[1].children)).toEqual(['sted', 'confocal', 'widefield'])
  })

  it('promotes a category whose parent is missing rather than dropping it', () => {
    const tree = buildCategoryTree([category('orphan', { parentId: 'deleted' })])
    expect(names(tree)).toEqual(['orphan'])
  })
})

describe('buildBrowsableTree', () => {
  const categories = [
    category('light'),
    category('holding', { parentId: 'light', isHidden: true }),
    category('confocal', { parentId: 'light' }),
    category('top-holding', { isHidden: true }),
    category('under-holding', { parentId: 'top-holding' }),
  ]

  it('leaves hidden categories out at every level', () => {
    const tree = buildBrowsableTree(categories)
    const all = tree.flatMap(subtreeIds)

    expect(all).not.toContain('holding')
    expect(all).not.toContain('top-holding')
    expect(names(tree[0].children)).toEqual(['confocal'])
  })

  it('keeps a visible category filed under a hidden one, at the top level', () => {
    expect(names(buildBrowsableTree(categories))).toEqual(['light', 'under-holding'])
  })

  it('does not disturb the list it was given', () => {
    buildBrowsableTree(categories)
    expect(categories).toHaveLength(5)
    expect(categories.find((c) => c.id === 'holding')?.isHidden).toBe(true)
  })
})

describe('browsableChildren', () => {
  it('lists the visible categories directly beneath one', () => {
    const categories = [
      category('light'),
      category('b', { parentId: 'light', orderIndex: 2 }),
      category('a', { parentId: 'light', orderIndex: 1 }),
      category('hidden', { parentId: 'light', isHidden: true }),
      category('grandchild', { parentId: 'a' }),
    ]
    expect(names(browsableChildren(categories, 'light'))).toEqual(['a', 'b'])
  })
})

describe('subtreeIds', () => {
  it('collects a node and everything beneath it', () => {
    const [light] = buildCategoryTree([
      category('light'),
      category('confocal', { parentId: 'light' }),
      category('stellaris', { parentId: 'confocal' }),
    ])
    expect(subtreeIds(light).sort()).toEqual(['confocal', 'light', 'stellaris'])
  })
})

describe('possibleParents', () => {
  const categories = [
    category('light'),
    category('confocal', { parentId: 'light' }),
    category('stellaris', { parentId: 'confocal' }),
    category('electron'),
  ]

  it('offers everything when the category is new', () => {
    expect(possibleParents(categories, null)).toHaveLength(4)
  })

  it('never offers a category itself or anything beneath it, which would make a loop', () => {
    expect(names(possibleParents(categories, 'light'))).toEqual(['electron'])
    expect(names(possibleParents(categories, 'confocal')).sort()).toEqual(['electron', 'light'])
  })
})

describe('moveAmongSiblings', () => {
  const cat = (id: string, orderIndex: number, parentId: string | null = null): Category => ({
    id,
    slug: id,
    name: id,
    description: '',
    parentId,
    orderIndex,
    isHidden: false,
  })

  it('swaps two neighbours and rewrites only those two', () => {
    const list = [cat('a', 0), cat('b', 1), cat('c', 2)]
    expect(moveAmongSiblings(list, 'c', -1)).toEqual([
      { id: 'c', orderIndex: 1 },
      { id: 'b', orderIndex: 2 },
    ])
  })

  it('does nothing at either end of the list', () => {
    const list = [cat('a', 0), cat('b', 1)]
    expect(moveAmongSiblings(list, 'a', -1)).toEqual([])
    expect(moveAmongSiblings(list, 'b', 1)).toEqual([])
    expect(moveAmongSiblings(list, 'missing', 1)).toEqual([])
  })

  /* Imported categories can all carry the same index and sort by name; a plain
     swap of two equal numbers would move nothing. */
  it('renumbers siblings that share an index so the move actually takes', () => {
    const list = [cat('alpha', 0), cat('beta', 0), cat('gamma', 0)]
    const changes = moveAmongSiblings(list, 'gamma', -1)

    const applied = list.map((entry) => ({
      ...entry,
      orderIndex: changes.find((change) => change.id === entry.id)?.orderIndex ?? entry.orderIndex,
    }))
    expect([...applied].sort(byOrder).map((entry) => entry.id)).toEqual(['alpha', 'gamma', 'beta'])
  })

  it('moves only among categories with the same parent', () => {
    const list = [cat('root-a', 0), cat('root-b', 1), cat('child-a', 0, 'root-a'), cat('child-b', 1, 'root-a')]
    expect(moveAmongSiblings(list, 'child-b', -1)).toEqual([
      { id: 'child-b', orderIndex: 0 },
      { id: 'child-a', orderIndex: 1 },
    ])
    expect(moveAmongSiblings(list, 'child-a', -1)).toEqual([])
  })
})

describe('ancestorsOf', () => {
  const cat = (id: string, parentId: string | null): Category => ({
    id,
    slug: id,
    name: id,
    description: '',
    parentId,
    orderIndex: 0,
    isHidden: false,
  })

  it('lists parents outermost first', () => {
    const list = [cat('light', null), cat('confocal', 'light'), cat('stellaris', 'confocal')]
    expect(ancestorsOf(list, list[2]).map((entry) => entry.id)).toEqual(['light', 'confocal'])
    expect(ancestorsOf(list, list[0])).toEqual([])
  })

  it('stops at a parent that is missing, and at a loop', () => {
    const orphan = cat('orphan', 'gone')
    expect(ancestorsOf([orphan], orphan)).toEqual([])

    const a = cat('a', 'b')
    const b = cat('b', 'a')
    expect(ancestorsOf([a, b], a).map((entry) => entry.id)).toEqual(['b'])
  })
})

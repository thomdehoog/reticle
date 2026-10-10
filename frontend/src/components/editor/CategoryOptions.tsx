import { byOrder } from '../../domain/category'
import type { Category } from '../../domain/types'

/**
 * The `<option>`s for choosing a category.
 *
 * Holding categories are listed here although they are left out of browsing:
 * filing a guide in one is exactly what they are for. They are marked so an
 * author can tell them from the categories readers see.
 */
export function CategoryOptions({ categories }: { categories: Category[] }) {
  return (
    <>
      {[...categories].sort(byOrder).map((category) => (
        <option key={category.id} value={category.id}>
          {category.name}
          {category.isHidden ? ' (hidden)' : ''}
        </option>
      ))}
    </>
  )
}

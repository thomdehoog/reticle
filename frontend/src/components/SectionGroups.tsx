/**
 * A section's groups, and the drag that decides which group a row is in.
 *
 * A group is a tag, and a row is in a group because the document carries that
 * tag. So dragging a row from one group into another is not a layout gesture
 * with a layout to store — it is an edit to the document's tags, and the
 * arrangement follows from it the way it follows from tagging in the editor.
 * Nothing here writes a section's contents anywhere.
 *
 * **One rule: a drag moves a row from wherever it is into the group it is
 * dropped on.** Dropped onto a group it did not come from, the document gains
 * that tag; if it came from a group, it loses that one. A guide sitting in ten
 * groups is left in the other nine, which is the whole reason ZMB's corpus is
 * arranged by tag — one LAS X procedure belongs under every instrument it
 * applies to, and dragging it out of one heading must not take it out of those.
 *
 * There is no drop target that means "no group". Taking a document out of every
 * group is not arranging a section, it is deciding the document has no subject,
 * and the tag field in its editor is where that is said.
 *
 * The rows move as the pointer crosses a group, so what is on screen while the
 * mouse is still down is the result of letting go. Only then is anything sent.
 *
 * Dragging is not reachable from a keyboard. The tag field in each document's
 * editor is, it reaches the same tags, and it is the answer for anybody who
 * cannot drag rather than a lesser version of this.
 *
 * Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>
 */

import { useState } from 'react'
import { Link } from 'react-router'

import { useApi, useAuth } from '../auth/AuthContext'
import { endpointKey, groupAnchor, groupHeading, type Endpoint, type Grouped } from '../domain/groups'
import { GuideRow, GuideRows, PageRow, type RowDrag } from './BrowseCards'
import { ErrorAlert } from './ui'

export function SectionGroups({ grouped, onChanged }: { grouped: Grouped; onChanged: () => void }) {
  const api = useApi()
  const { can } = useAuth()
  /* The right the server asks for, which is the right to change the document's
     tags — the same one the tag field in its editor needs. Not `admin`: this
     reaches nothing that screen does not already reach. */
  const canArrange = can('author')

  const [dragging, setDragging] = useState<{ endpoint: Endpoint; from: string | null } | null>(null)
  /** The group the pointer is over, once it is somewhere the row is not already. */
  const [over, setOver] = useState<string | null>(null)
  const [failure, setFailure] = useState<unknown>(null)

  const shown = over && dragging ? withMoved(grouped, dragging.endpoint, dragging.from, over) : grouped

  /**
   * Send the arrangement the page is already showing.
   *
   * `onChanged` is not called on success: the rows moved when the pointer
   * crossed the group, and re-reading the section to draw the same thing is a
   * flicker for nothing. On failure it is, because then the screen is showing an
   * arrangement the server refused.
   */
  async function commit(endpoint: Endpoint, from: string | null, to: string) {
    const tags = [...endpoint.tags.filter((tag) => tag !== from && tag !== to), to]
    setFailure(null)
    try {
      if (endpoint.kind === 'guide') {
        await api.setGuideTags(endpoint.id, tags, endpoint.guide.updatedAt)
      } else {
        await api.setPageTags(endpoint.id, tags, endpoint.page.updatedAt)
      }
      /* The row's own `updatedAt` has moved on, and the copy this page holds
         has not — a second drag of the same row would carry the old one and be
         refused as stale. Re-reading is what makes two drags in a row work. */
      onChanged()
    } catch (cause) {
      setFailure(cause)
      onChanged()
    }
  }

  function rowProps(endpoint: Endpoint, from: string | null) {
    if (!canArrange) return {}
    return {
      draggable: true,
      onDragStart: (event: React.DragEvent) => {
        setDragging({ endpoint, from })
        event.dataTransfer.effectAllowed = 'move'
        /* Firefox will not start a drag without data on it. */
        event.dataTransfer.setData('text/plain', endpointKey(endpoint))
      },
      /* Cancelled — dropped on nothing, or Escape. It fires on the row that
         started the drag, which is why nothing is committed from here: showing
         the result means the row is already drawn inside the group it would
         land in, so the element this would arrive at has been replaced by that
         one and the event has nowhere to go. The drop target is a stable
         element and answers for the move instead. */
      onDragEnd: () => {
        setDragging(null)
        setOver(null)
      },
    }
  }

  function groupProps(tag: string) {
    if (!canArrange) return {}
    return {
      /* `dragEnter` and not `dragOver`: entering fires once per group crossed,
         where `dragOver` fires every few pixels. */
      onDragEnter: () => {
        if (dragging) setOver(tag)
      },
      onDragOver: (event: React.DragEvent) => {
        if (!dragging) return
        /* Both are needed before a drop is allowed to happen here at all. */
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
      },
      /* Leaving the group takes the preview with it, so a drag abandoned
         somewhere else does not leave the page showing a move that never
         happened. Guarded on where the pointer went: this fires on the way
         *into* every row inside the group as well, because the event bubbles,
         and clearing on those would undo the preview the moment it was made. */
      onDragLeave: (event: React.DragEvent) => {
        const to = event.relatedTarget
        if (to instanceof Node && event.currentTarget.contains(to)) return
        setOver((current) => (current === tag ? null : current))
      },
      onDrop: (event: React.DragEvent) => {
        event.preventDefault()
        const held = dragging
        setDragging(null)
        setOver(null)
        if (held && tag !== held.from) void commit(held.endpoint, held.from, tag)
      },
    }
  }

  return (
    <>
      <ErrorAlert error={failure} />

      {/* Nothing tagged yet, above the groups and under no heading — a section
          part-tagged is an ordinary state, not one to invent a name for. It is
          a place to drag out of and not a place to drop: see the rule above. */}
      {shown.loose.length > 0 && (
        <section className="section section--group">
          <GuideRows>
            {shown.loose.map((endpoint) => (
              <EndpointRow key={endpointKey(endpoint)} endpoint={endpoint} {...rowProps(endpoint, null)} />
            ))}
          </GuideRows>
        </section>
      )}

      {shown.groups.map((group) => (
        <section
          className={`section section--group${over === group.tag ? ' section--group-target' : ''}`}
          key={group.tag}
          id={groupAnchor(group.tag)}
          {...groupProps(group.tag)}
        >
          <h3 className="section__title">
            <Link to={`/t/${encodeURIComponent(group.tag)}`}>{groupHeading(group.tag)}</Link>
          </h3>
          <GuideRows>
            {group.items.map((endpoint) => (
              <EndpointRow
                key={`${group.tag}-${endpointKey(endpoint)}`}
                endpoint={endpoint}
                {...rowProps(endpoint, group.tag)}
              />
            ))}
          </GuideRows>
        </section>
      ))}
    </>
  )
}

/**
 * The arrangement as it would be if the row were let go here.
 *
 * A group the row was the last member of is kept, empty, until the drag ends.
 * Removing it mid-drag would pull every group below it up under the pointer,
 * and the drop would land somewhere the hand did not aim at; it goes when the
 * section is re-read.
 */
function withMoved(grouped: Grouped, endpoint: Endpoint, from: string | null, to: string): Grouped {
  const key = endpointKey(endpoint)
  const without = (items: Endpoint[]) => items.filter((item) => endpointKey(item) !== key)

  return {
    loose: from === null ? without(grouped.loose) : grouped.loose,
    groups: grouped.groups.map((group) => {
      if (group.tag === from) return { ...group, items: without(group.items) }
      if (group.tag !== to) return group
      /* Where a wiki goes in a group it is joining: with the wikis, at the top,
         which is where the grouping puts them. */
      const rest = without(group.items)
      const at = endpoint.kind === 'wiki' ? rest.findIndex((item) => item.kind === 'guide') : -1
      const items = [...rest]
      items.splice(at < 0 ? items.length : at, 0, endpoint)
      return { ...group, items }
    }),
  }
}

/**
 * One row, drawn as whichever kind of thing it points at.
 *
 * The union is narrowed here and nowhere else. Grouping and the drag work on
 * `Endpoint` alone — a guide and a wiki differ in how they are drawn and in
 * nothing else this screen cares about.
 */
function EndpointRow({ endpoint, ...dragging }: { endpoint: Endpoint } & RowDrag) {
  return endpoint.kind === 'guide' ? (
    <GuideRow guide={endpoint.guide} {...dragging} />
  ) : (
    <PageRow page={endpoint.page} {...dragging} />
  )
}

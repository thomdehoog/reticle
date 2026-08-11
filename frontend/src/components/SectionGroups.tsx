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
import { slugifyTag } from './editor/TagInput'
import { IconEdit, IconTrash } from './icons'
import { ErrorAlert, Modal } from './ui'

export function SectionGroups({
  grouped,
  categoryId,
  placedTags,
  onPendingRenamed,
  justMade,
  onChanged,
}: {
  grouped: Grouped
  /** The section these groups belong to, which is what owns their order. */
  categoryId: string
  /** The tags an administrator has placed (`category.tagOrder`), so a rename
      can keep the group's position instead of dropping it to the bottom. */
  placedTags: string[]
  /** A still-empty group lives only in the caller's hands, so renaming one is
      the caller's to record — there is nothing on the server to write. */
  onPendingRenamed: (from: string, to: string) => void
  /** The group the caller just made, whose name should open ready to be
      typed over — making a group and naming it are one gesture. */
  justMade?: string | null
  onChanged: () => void
}) {
  const api = useApi()
  const { can } = useAuth()
  /* The right the server asks for, which is the right to change the document's
     tags — the same one the tag field in its editor needs. Not `admin`: this
     reaches nothing that screen does not already reach. */
  const canArrange = can('author')
  /* Restacking the page is the section's, and every reader gets it — so it is
     the same rank as making and deleting one. */
  const canReorder = can('admin')

  const [dragging, setDragging] = useState<{ endpoint: Endpoint; from: string | null } | null>(null)
  /** The group being dragged up or down, as opposed to a row being dragged into one. */
  const [lifted, setLifted] = useState<string | null>(null)
  /** The group the pointer is over, once it is somewhere the row is not already. */
  const [over, setOver] = useState<string | null>(null)
  const [failure, setFailure] = useState<unknown>(null)
  /** The heading being edited in place, and what it says right now. */
  const [renaming, setRenaming] = useState<{ tag: string; value: string } | null>(null)
  /** The row whose archiving is awaiting the administrator's second thought. */
  const [archiving, setArchiving] = useState<Endpoint | null>(null)

  /* Adjusted during render, as the stack order is: the caller has just made a
     group, and its name opens in the editing state without a paint of the
     plain heading in between. */
  const [greeted, setGreeted] = useState<string | null>(null)
  if ((justMade ?? null) !== greeted) {
    setGreeted(justMade ?? null)
    if (justMade) setRenaming({ tag: justMade, value: groupHeading(justMade) })
  }

  /**
   * The stack as it stands on screen, which during a drag is ahead of the
   * server. A group moves as soon as the pointer is over the place it would
   * land, so what is shown while the mouse is still down is the result of
   * letting go.
   */
  const [order, setOrder] = useState(grouped.groups.map((group) => group.tag))
  /* Adjusted during render rather than in an effect, as the section grid's is:
     an effect would paint the stale order first and then correct it. */
  const [rendered, setRendered] = useState(grouped)
  if (rendered !== grouped) {
    setRendered(grouped)
    setOrder(grouped.groups.map((group) => group.tag))
  }

  const stacked = {
    loose: grouped.loose,
    groups: [...grouped.groups].sort((a, b) => order.indexOf(a.tag) - order.indexOf(b.tag)),
  }
  const shown = over && dragging ? withMoved(stacked, dragging.endpoint, dragging.from, over) : stacked

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

  /**
   * The rename, which is nothing but retagging the rows.
   *
   * Enter commits; Escape or clicking away cancels — one path into the write,
   * so a blur after Enter cannot send it twice. A group an administrator has
   * placed keeps its place: the order is rewritten with the new name where
   * the old one stood, because a heading must not sink to the bottom of the
   * stack for being corrected. An empty group has nothing to write and is the
   * caller's to rename.
   */
  async function commitRename(group: { tag: string; items: Endpoint[] }, value: string) {
    setRenaming(null)
    /* Through the same slugifier the tag input types with: a tag is a slug,
       and the server refuses any other shape. */
    const next = slugifyTag(value)
    if (next === '' || next === group.tag) return
    if (group.items.length === 0) {
      onPendingRenamed(group.tag, next)
      return
    }
    setFailure(null)
    try {
      await Promise.all(
        group.items.map((endpoint) => {
          const tags = endpoint.tags.map((tag) => (tag === group.tag ? next : tag))
          return endpoint.kind === 'guide'
            ? api.setGuideTags(endpoint.id, tags, endpoint.guide.updatedAt)
            : api.setPageTags(endpoint.id, tags, endpoint.page.updatedAt)
        }),
      )
      if (placedTags.includes(group.tag)) {
        await api.setTagOrder(
          categoryId,
          placedTags.map((tag) => (tag === group.tag ? next : tag)),
        )
      }
      onChanged()
    } catch (cause) {
      setFailure(cause)
      onChanged()
    }
  }

  /**
   * A document born where the author is standing: in this section, wearing
   * this group's tag, as a draft — no dialog, nothing asked. The row appears
   * in the group and opening it is how it gets written; its title is edited
   * there, which is also where every other fact about it lives.
   */
  async function createInGroup(tag: string, kind: 'guide' | 'page') {
    setFailure(null)
    try {
      if (kind === 'guide') {
        const guide = await api.createGuide('New guide', categoryId)
        await api.setGuideTags(guide.id, [tag], guide.updatedAt)
      } else {
        const page = await api.createPage({ title: 'New page', categoryId, isLanding: false })
        await api.setPageTags(page.id, [tag], page.updatedAt)
      }
      onChanged()
    } catch (cause) {
      setFailure(cause)
      onChanged()
    }
  }

  async function confirmArchive(endpoint: Endpoint) {
    setArchiving(null)
    setFailure(null)
    try {
      if (endpoint.kind === 'guide') {
        await api.archiveGuide(endpoint.id)
      } else {
        await api.archivePage(endpoint.id)
      }
      onChanged()
    } catch (cause) {
      setFailure(cause)
      onChanged()
    }
  }

  /**
   * What a section page hangs beside a row: the way into its editor for any
   * author, and for an administrator the same archive the editor's lifecycle
   * row offers — the server refuses an author's archive anyway, and a button
   * that always fails is a lie.
   */
  function rowActions(endpoint: Endpoint) {
    if (!canArrange) return undefined
    const title = endpoint.kind === 'guide' ? endpoint.guide.title : endpoint.page.title
    return (
      <>
        <Link
          className="button button--sm"
          aria-label={`Edit ${title}`}
          to={endpoint.kind === 'guide' ? `/g/${endpoint.id}/edit` : `/w/${endpoint.id}/edit`}
        >
          <IconEdit size={14} />
        </Link>
        {canReorder && (
          <button
            type="button"
            className="button button--sm"
            aria-label={`Archive ${title}`}
            onClick={() => setArchiving(endpoint)}
          >
            <IconTrash size={14} />
          </button>
        )}
      </>
    )
  }

  /** Move the lifted group to where `target` currently sits, on screen only. */
  function previewLift(target: string) {
    setOrder((current) => {
      const from = current.indexOf(lifted!)
      const to = current.indexOf(target)
      if (from < 0 || to < 0 || from === to) return current
      const next = [...current]
      const [moved] = next.splice(from, 1)
      next.splice(to, 0, moved)
      return next
    })
  }

  /**
   * Write down the stack the page is already showing.
   *
   * The whole order, not the one group that moved: the index is a position and
   * not a weight, so writing one and leaving the rest would put two groups on
   * the same number. `onChanged` only on failure, where the screen is showing an
   * arrangement the server refused.
   */
  async function commitOrder() {
    setFailure(null)
    try {
      await api.setTagOrder(categoryId, order)
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

  /**
   * The panel, which is two drop targets wearing one element.
   *
   * A row dropped here joins this group; a group dropped here takes this one's
   * place in the stack. Which of the two is happening is not read off the event
   * — it is whichever drag is in progress, and only one ever is.
   *
   * The panel is draggable so that grabbing it anywhere but a row lifts the
   * group. The browser starts the drag from the innermost draggable element, so
   * a row still moves as a row; `dragStart` bubbles up here from it, which is
   * what the target check is for.
   */
  function groupProps(tag: string) {
    if (!canArrange && !canReorder) return {}
    return {
      draggable: canReorder,
      onDragStart: (event: React.DragEvent) => {
        if (event.target !== event.currentTarget) return
        setLifted(tag)
        event.dataTransfer.effectAllowed = 'move'
        /* Firefox will not start a drag without data on it. */
        event.dataTransfer.setData('text/plain', tag)
      },
      onDragEnd: (event: React.DragEvent) => {
        if (event.target !== event.currentTarget) return
        setLifted(null)
        void commitOrder()
      },
      /* `dragEnter` and not `dragOver`: entering fires once per group crossed,
         where `dragOver` fires every few pixels and would move the same group
         over and over while the pointer sat still. */
      onDragEnter: () => {
        if (dragging) setOver(tag)
        else if (lifted && lifted !== tag) previewLift(tag)
      },
      onDragOver: (event: React.DragEvent) => {
        if (!dragging && !lifted) return
        /* Both are needed before a drop is allowed to happen here at all, which
           is what makes `dragEnd` mean "let go here" rather than "cancelled". */
        event.preventDefault()
        event.dataTransfer.dropEffect = 'move'
      },
      /* Leaving the group takes the row preview with it, so a drag abandoned
         somewhere else does not leave the page showing a move that never
         happened. Guarded on where the pointer went: this fires on the way
         *into* every row inside the group as well, because the event bubbles,
         and clearing on those would undo the preview the moment it was made.

         A lifted group is not cleared here. Its preview is the stack itself,
         which has nowhere to revert to mid-drag, and `dragEnd` fires on the
         panel — an element that is moved rather than replaced, so unlike a row
         it is still there to receive it. */
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
              <EndpointRow
                key={endpointKey(endpoint)}
                endpoint={endpoint}
                actions={rowActions(endpoint)}
                {...rowProps(endpoint, null)}
              />
            ))}
          </GuideRows>
        </section>
      )}

      {shown.groups.map((group) => (
        <section
          className={[
            'section section--group',
            over === group.tag ? 'section--group-target' : '',
            lifted === group.tag ? 'section--group-lifted' : '',
          ]
            .join(' ')
            .trim()}
          key={group.tag}
          id={groupAnchor(group.tag)}
          {...groupProps(group.tag)}
        >
          <div className="section__head">
            {renaming?.tag === group.tag ? (
              /* The heading as a text box, which is all a rename should feel
                 like. Enter commits, Escape or clicking away cancels. */
              <input
                className="input section__rename"
                aria-label="Group name"
                autoFocus
                /* Selected on arrival, so a just-made group's placeholder
                   name is replaced by typing rather than deleted first. */
                onFocus={(event) => event.target.select()}
                value={renaming.value}
                onChange={(event) => setRenaming({ tag: group.tag, value: event.target.value })}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void commitRename(group, renaming.value)
                  if (event.key === 'Escape') setRenaming(null)
                }}
                onBlur={() => setRenaming(null)}
              />
            ) : (
              /* The pencil lives beside the name it renames — a control next
                 to the thing it changes needs no explaining — while the two
                 creations sit at the strip's far end. */
              <span className="section__name">
                <h3 className="section__title">
                  <Link to={`/t/${encodeURIComponent(group.tag)}`}>{groupHeading(group.tag)}</Link>
                </h3>
                {/* Renaming a placed group retags other people's documents, so
                    it is an administrator's; a still-empty group belongs to
                    whoever just made it, and naming it is finishing the making. */}
                {(canReorder || group.items.length === 0) && (
                  <button
                    type="button"
                    className="button button--sm"
                    aria-label={`Rename ${groupHeading(group.tag)}`}
                    onClick={() => setRenaming({ tag: group.tag, value: groupHeading(group.tag) })}
                  >
                    <IconEdit size={14} />
                  </button>
                )}
              </span>
            )}
            {canArrange && (
              <span className="section__tools">
                <button
                  type="button"
                  className="button button--sm"
                  aria-label={`Add a guide to ${groupHeading(group.tag)}`}
                  onClick={() => void createInGroup(group.tag, 'guide')}
                >
                  Add guide
                </button>
                <button
                  type="button"
                  className="button button--sm"
                  aria-label={`Add a wiki to ${groupHeading(group.tag)}`}
                  onClick={() => void createInGroup(group.tag, 'page')}
                >
                  Add wiki
                </button>
              </span>
            )}
          </div>
          {group.items.length > 0 ? (
            <GuideRows>
              {group.items.map((endpoint) => (
                <EndpointRow
                  key={`${group.tag}-${endpointKey(endpoint)}`}
                  endpoint={endpoint}
                  actions={rowActions(endpoint)}
                  {...rowProps(endpoint, group.tag)}
                />
              ))}
            </GuideRows>
          ) : (
            /* A group just made, waiting for its first document — the two
               buttons above are how one arrives, and a drag lands here too. */
            <p className="section__empty">Nothing in this group yet.</p>
          )}
        </section>
      ))}

      {archiving && (
        <Modal
          title={`Archive ${archiving.kind === 'guide' ? archiving.guide.title : archiving.page.title}?`}
          onClose={() => setArchiving(null)}
        >
          <p className="field__hint" style={{ marginBottom: '1rem' }}>
            It disappears from every listing and search. Nothing is deleted — the content and its
            history are kept.
          </p>
          <div className="page-actions">
            <button
              type="button"
              className="button button--danger"
              onClick={() => void confirmArchive(archiving)}
            >
              {archiving.kind === 'guide' ? 'Archive guide' : 'Archive page'}
            </button>
            <button type="button" className="button" onClick={() => setArchiving(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
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
function EndpointRow({
  endpoint,
  actions,
  ...dragging
}: { endpoint: Endpoint; actions?: React.ReactNode } & RowDrag) {
  return endpoint.kind === 'guide' ? (
    <GuideRow guide={endpoint.guide} actions={actions} {...dragging} />
  ) : (
    <PageRow page={endpoint.page} actions={actions} {...dragging} />
  )
}

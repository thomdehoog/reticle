/**
 * Which version of a document this is, and when it became that.
 *
 * Both facts are operational rather than decorative. Somebody standing at an
 * instrument needs to know whether the procedure in front of them is still the
 * current one, and two people comparing notes need something they can name:
 * "version 7" is checkable, "the one I read last week" is not.
 *
 * It is a separate file because a guide and a wiki page both need it and must
 * show it identically. A reader should not have to learn that the date on one
 * screen means something different from the date on another — and the rule
 * about *which* date that is, below, is exactly the kind of thing that drifts
 * once it has been written out twice.
 */

export interface RevisionProps {
  version: number
  /** When this became the published version. Null while it is a draft. */
  publishedAt: string | null
  /** When it was last touched, published or not. */
  updatedAt: string
}

/**
 * A date nobody can misread.
 *
 * `2 August 2026`, never `02/08/2026`, because this institute reads German and
 * English and those two conventions disagree about which number is the month.
 * The month is spelled out, so there is nothing to get wrong.
 */
export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

export function Revision({ version, publishedAt, updatedAt }: RevisionProps) {
  /*
   * A published document is stamped with when it was published, not when it was
   * last edited. What a reader wants to know is when the procedure in front of
   * them became the procedure; `updatedAt` moves when an author fixes a typo in
   * a draft, which tells them nothing and would make a stable procedure look
   * freshly changed.
   *
   * A draft has no publication date, so it shows the edit date and says so.
   */
  const published = publishedAt !== null
  const when = published ? publishedAt : updatedAt

  return (
    <span className="revision">
      v{version}
      <span className="revision__sep" aria-hidden="true" />
      {published ? '' : 'edited '}
      <time dateTime={when}>{formatDay(when)}</time>
    </span>
  )
}

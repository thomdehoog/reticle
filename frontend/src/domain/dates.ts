/**
 * How Reticle writes a date for a person.
 *
 * Spelled with the month as a word — "3 Mar 2026" — because ZMB is an
 * international facility: `03/04/2026` is March to half its users and April to
 * the other half, and a publication date is exactly the thing that must not be
 * read two ways. The reader's own locale still decides the order and the words.
 */

const DATE: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short', year: 'numeric' }
const TIME: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit' }

export function formatDate(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleDateString(undefined, DATE)
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { ...DATE, ...TIME })
}

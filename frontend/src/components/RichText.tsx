/**
 * The small amount of formatting a guide's own words are allowed.
 *
 * Bold, italic, links, and a line break. Nothing else — no headings, no
 * pictures, no tables, no code fences, no embedded guide lists. A bullet is one
 * instruction beside one mark on a picture, and a heading inside it would be a
 * heading inside a sentence.
 *
 * It is a separate component from `MarkdownBody` rather than a flag on it
 * because the two answer different questions. A wiki page is a document and may
 * contain document things. A bullet, an introduction and a step's title are
 * sentences, and the list of what a sentence may contain is short and closed.
 * Written as an option on the other renderer, that list would be one prop away
 * from being opened by accident.
 *
 * What both share is the property that matters: markdown is rendered to React
 * elements, never to an HTML string. There is no `dangerouslySetInnerHTML`, no
 * sanitiser to keep up to date, and raw HTML in the source is ignored rather
 * than escaped-then-hopefully-caught. An author who types `<script>` gets the
 * characters they typed.
 */

import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router'

/** A path inside Reticle. `//host` is not one, however much it looks like one. */
function isInternalPath(href: string): boolean {
  return href.startsWith('/') && !href.startsWith('//')
}

function InlineLink({ href, children }: { href?: string; children?: React.ReactNode }) {
  if (href && isInternalPath(href)) {
    return <Link to={href}>{children}</Link>
  }

  /*
   * react-markdown neutralises a URL it rejects — `javascript:`, `data:` — by
   * rewriting it to the empty string, and `<a href="">` reloads the current
   * page. A reader who clicked one would lose their place in the procedure,
   * which reads as a bug rather than as the refusal it is. Rendering the words
   * without a link says the truth: there is nowhere to go.
   */
  if (!href) return <>{children}</>

  return (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  )
}

/**
 * Everything a sentence may not contain, rendered as its own text instead.
 *
 * Returning the children rather than null matters: an author who types `# 5`
 * meaning "five bar" has written a heading as far as the parser is concerned,
 * and silently dropping it would delete a real instruction from a procedure.
 */
function AsPlainText({ children }: { children?: React.ReactNode }) {
  return <>{children}</>
}

const INLINE_ONLY = {
  a: InlineLink,
  h1: AsPlainText,
  h2: AsPlainText,
  h3: AsPlainText,
  h4: AsPlainText,
  h5: AsPlainText,
  h6: AsPlainText,
  img: () => null,
  pre: AsPlainText,
  code: AsPlainText,
  blockquote: AsPlainText,
  hr: () => null,
}

/**
 * One sentence's worth of formatting, with no paragraph wrapper.
 *
 * Used where the text is already inside something — a bullet, a step title —
 * and a `<p>` would break the layout it sits in.
 */
export function RichInline({ text }: { text: string }) {
  return (
    <ReactMarkdown components={{ ...INLINE_ONLY, p: AsPlainText }}>{text}</ReactMarkdown>
  )
}

/**
 * The same formatting, keeping paragraphs.
 *
 * For a guide's introduction, which is prose: an author who leaves a blank line
 * between two thoughts means two paragraphs, and running them together was the
 * old behaviour and a bug.
 */
export function RichText({ text }: { text: string }) {
  return <ReactMarkdown components={INLINE_ONLY}>{text}</ReactMarkdown>
}

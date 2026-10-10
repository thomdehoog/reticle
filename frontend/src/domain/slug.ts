/**
 * The tag slug rule, mirrored from `tag_slug` in backend/app/slugs.py.
 *
 * The editor slugs a tag before it sends it — to spot duplicates and to match
 * suggestions — so the two implementations have to agree character for
 * character, or a tag typed here would file the guide under a different tag
 * from the one a wiki page asks for. backend/tests/data/tag_slug_cases.json is
 * read by both test suites to hold them together.
 */

/**
 * Letters whose readable ASCII form is not what stripping the accent gives.
 * "Präparation" is spelt "Praeparation" where umlauts are unavailable; a bare
 * "praparation" is not a word a German reader would guess. The same table, in
 * the same order of operations, as the server's.
 */
const TRANSLITERATIONS: Record<string, string> = {
  ä: 'ae',
  ö: 'oe',
  ü: 'ue',
  ß: 'ss',
  æ: 'ae',
  œ: 'oe',
  ø: 'o',
  å: 'a',
  đ: 'd',
  ð: 'd',
  þ: 'th',
  ł: 'l',
}

const TRANSLITERATED = new RegExp(`[${Object.keys(TRANSLITERATIONS).join('')}]`, 'g')

/** Lower-case and reduce accented Latin letters to plain ones. */
export function fold(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .normalize('NFC')
    .replace(TRANSLITERATED, (letter) => TRANSLITERATIONS[letter])
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
}

export function slugifyTag(value: string): string {
  return fold(value)
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

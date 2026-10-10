import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * Without an icon of its own the browser asks for /favicon.ico, and the static
 * server answers every unknown path with the app shell — so the "icon" was an
 * HTML page. These pin the two halves of the fix: the file exists where Vite
 * copies it from, and the shell points at it.
 */
const root = resolve(__dirname, '..')

describe('favicon', () => {
  it('is linked from the app shell as a same-origin SVG', () => {
    const shell = new DOMParser().parseFromString(
      readFileSync(resolve(root, 'index.html'), 'utf-8'),
      'text/html',
    )
    const link = shell.querySelector('link[rel="icon"]')

    expect(link?.getAttribute('href')).toBe('/favicon.svg')
    expect(link?.getAttribute('type')).toBe('image/svg+xml')
  })

  it('is a well-formed SVG that loads nothing and runs nothing', () => {
    const source = readFileSync(resolve(root, 'public/favicon.svg'), 'utf-8')
    const icon = new DOMParser().parseFromString(source, 'image/svg+xml')

    expect(icon.querySelector('parsererror')).toBeNull()
    expect(icon.documentElement.tagName).toBe('svg')
    expect(icon.documentElement.getAttribute('viewBox')).toBe('0 0 32 32')
    // The page's CSP grants images nothing but 'self'; the icon must not need more.
    expect(source).not.toMatch(/<script|<style|href=|url\(/i)
  })
})

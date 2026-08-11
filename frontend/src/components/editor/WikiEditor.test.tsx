/**
 * The writing surface's contract with the page that owns it.
 *
 * Two promises carry everything: `onChange` fires with fresh markdown on every
 * real edit, and never otherwise — not on opening, not when the owner replaces
 * the value from outside. The first is what autosave rides on; the second is
 * what keeps an imported page from being re-serialised because somebody looked
 * at it.
 *
 * jsdom cannot type into contenteditable, so edits are driven the way the bar
 * drives them — commands — which is also exactly the mapping these tests own.
 */

import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useEffect, useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { useEditor } from '@tiptap/react'

import { WikiEditor, WikiEditorBar } from './WikiEditor'
import { wikiEditorExtensions } from './wikiEditorKit'
import { createFakeServer, guideFixture } from '../../test/fakeServer'
import { renderWithApp } from '../../test/harness'

function server() {
  return createFakeServer({
    guides: [
      guideFixture({
        id: 'g-startup',
        slug: 'stellaris-startup',
        title: 'Stellaris start-up',
        status: 'published',
      }),
    ],
  })
}

describe('WikiEditor', () => {
  it('reports nothing when a page is merely opened', async () => {
    const onChange = vi.fn()
    renderWithApp(<WikiEditor value={'## Hello\n\nSome words.'} onChange={onChange} />, {
      fetchImpl: server().fetchImpl,
    })

    expect(await screen.findByText('Some words.')).toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('takes an outside replacement without calling it an edit', async () => {
    const onChange = vi.fn()
    function Stage() {
      const [value, setValue] = useState('The first wording.')
      return (
        <>
          <button type="button" onClick={() => setValue('Their wording.')}>
            Use theirs
          </button>
          <WikiEditor value={value} onChange={onChange} />
        </>
      )
    }
    const user = userEvent.setup()
    renderWithApp(<Stage />, { fetchImpl: server().fetchImpl })

    expect(await screen.findByText('The first wording.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use theirs' }))

    expect(await screen.findByText('Their wording.')).toBeInTheDocument()
    expect(screen.queryByText('The first wording.')).not.toBeInTheDocument()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('writes a heading when the author picks one', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<WikiEditor value="Getting started" onChange={onChange} />, {
      fetchImpl: server().fetchImpl,
    })
    await screen.findByText('Getting started')

    await user.click(screen.getByRole('button', { name: 'Text style' }))
    await user.click(screen.getByRole('button', { name: 'Heading' }))

    expect(onChange).toHaveBeenLastCalledWith('## Getting started')
  })

  it('inserts a guide list through its dialog', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<WikiEditor value="" onChange={onChange} />, { fetchImpl: server().fetchImpl })

    await user.click(await screen.findByRole('button', { name: 'More' }))
    await user.click(screen.getByRole('button', { name: 'Insert guide list' }))
    const dialog = within(screen.getByRole('dialog'))
    await user.type(dialog.getByLabelText('Add a tag'), 'stellaris{Enter}')
    await user.click(dialog.getByRole('button', { name: 'Insert' }))

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(
        expect.stringContaining('```guidelist\ntags: stellaris\n```'),
      ),
    )
  })

  it('links a guide found by its title', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<WikiEditor value="" onChange={onChange} />, { fetchImpl: server().fetchImpl })

    await user.click(await screen.findByRole('button', { name: 'Link a guide' }))
    await user.type(screen.getByLabelText('Search guides'), 'stellaris')
    await user.click(await screen.findByRole('button', { name: /Stellaris start-up/ }))

    await waitFor(() =>
      expect(onChange).toHaveBeenLastCalledWith(
        expect.stringContaining('[Stellaris start-up](/g/stellaris-startup)'),
      ),
    )
  })

  it('offers the markdown source from the overflow', async () => {
    const onSourceView = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<WikiEditor value="" onChange={vi.fn()} onSourceView={onSourceView} />, {
      fetchImpl: server().fetchImpl,
    })

    await user.click(await screen.findByRole('button', { name: 'More' }))
    await user.click(screen.getByRole('button', { name: 'Edit markdown source' }))

    expect(onSourceView).toHaveBeenCalledOnce()
  })
})

/**
 * The bar against a real selection. The harness selects the whole document the
 * way a hand would drag over it, then the buttons do their work — which pins
 * the mapping from each control to the markdown it produces.
 */
function BarStage({ content, onMarkdown }: { content: string; onMarkdown: (md: string) => void }) {
  const editor = useEditor({
    extensions: wikiEditorExtensions(),
    content,
    onUpdate({ editor }) {
      onMarkdown(
        (editor.storage as unknown as { markdown: { getMarkdown(): string } }).markdown.getMarkdown(),
      )
    },
  })

  useEffect(() => {
    editor?.commands.selectAll()
  }, [editor])

  if (!editor) return null
  return <WikiEditorBar editor={editor} />
}

describe('WikiEditorBar', () => {
  it('bolds the selection and says so on the button', async () => {
    const onMarkdown = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<BarStage content="quiet words" onMarkdown={onMarkdown} />, {
      fetchImpl: server().fetchImpl,
    })

    const bold = await screen.findByRole('button', { name: 'Bold' })
    expect(bold).toHaveAttribute('aria-pressed', 'false')
    await user.click(bold)

    expect(onMarkdown).toHaveBeenLastCalledWith('**quiet words**')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Bold' })).toHaveAttribute('aria-pressed', 'true'),
    )
  })

  it('turns the selection into a bulleted list', async () => {
    const onMarkdown = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<BarStage content="one thing" onMarkdown={onMarkdown} />, {
      fetchImpl: server().fetchImpl,
    })

    await user.click(await screen.findByRole('button', { name: 'Bulleted list' }))

    expect(onMarkdown).toHaveBeenLastCalledWith('- one thing')
  })

  it('links the selection to the address the author gives', async () => {
    const onMarkdown = vi.fn()
    const user = userEvent.setup()
    renderWithApp(<BarStage content="the booking page" onMarkdown={onMarkdown} />, {
      fetchImpl: server().fetchImpl,
    })

    await user.click(await screen.findByRole('button', { name: 'Link' }))
    await user.type(screen.getByLabelText('Address'), '/w/booking')
    await user.click(screen.getByRole('button', { name: 'Insert link' }))

    expect(onMarkdown).toHaveBeenLastCalledWith('[the booking page](/w/booking)')
  })
})

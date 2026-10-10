/**
 * The wiki editor's writing tools: the toolbar, the two panes, and pictures.
 * Saving, conflicts and publishing are in `PageEditorPage.test.tsx`.
 */

import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  categoryFixture,
  createFakeServer,
  guideFixture,
  pageFixture,
  type FakeServer,
} from '../test/fakeServer'
import { renderApp } from '../test/harness'

const DRAFT = pageFixture({ status: 'draft', publishedAt: null, version: 0 })

function renderEditor(server: FakeServer) {
  return renderApp({ route: '/w/p-objectives/edit', server })
}

async function source() {
  return (await screen.findByLabelText('Page content (Markdown)')) as HTMLTextAreaElement
}

function withBody(body: string) {
  return createFakeServer({ pages: [pageFixture({ ...DRAFT, body })] })
}

function selection(box: HTMLTextAreaElement): string {
  return box.value.slice(box.selectionStart, box.selectionEnd)
}

describe('the wiki toolbar', () => {
  it('is a labelled toolbar', async () => {
    renderEditor(withBody(''))
    await source()

    expect(screen.getByRole('toolbar', { name: 'Formatting' })).toBeInTheDocument()
  })

  it('turns the line under the cursor into a heading, and back', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('Intro.\nCleaning the objective'))

    const box = await source()
    box.setSelectionRange(15, 15)
    await user.click(screen.getByRole('button', { name: 'Heading' }))
    expect(box).toHaveValue('Intro.\n## Cleaning the objective')
    expect(screen.getByRole('heading', { level: 2, name: 'Cleaning the objective' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Heading' }))
    expect(box).toHaveValue('Intro.\nCleaning the objective')
  })

  it('makes a subheading', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('Lens paper'))

    const box = await source()
    await user.click(screen.getByRole('button', { name: 'Subheading' }))

    expect(box).toHaveValue('### Lens paper')
  })

  it('makes a bulleted and a numbered list of the selected lines', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('Air\nWater\nOil'))

    const box = await source()
    box.setSelectionRange(0, box.value.length)
    await user.click(screen.getByRole('button', { name: 'List' }))
    expect(box).toHaveValue('- Air\n- Water\n- Oil')

    await user.click(screen.getByRole('button', { name: 'Numbered list' }))
    expect(box).toHaveValue('1. Air\n2. Water\n3. Oil')
    expect(within(screen.getByRole('region', { name: 'Preview' })).getAllByRole('listitem')).toHaveLength(3)
  })

  it('italicises the selection and quotes a line', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('Never press.'))

    const box = await source()
    box.setSelectionRange(0, 5)
    await user.click(screen.getByRole('button', { name: 'Italic' }))
    expect(box).toHaveValue('_Never_ press.')

    await user.click(screen.getByRole('button', { name: 'Quote' }))
    expect(box).toHaveValue('> _Never_ press.')
  })

  it('links the selected words and leaves the address ready to be typed', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('See the booking rules.'))

    const box = await source()
    box.setSelectionRange(8, 21)
    await user.click(screen.getByRole('button', { name: 'Link' }))

    expect(box).toHaveValue('See the [booking rules](https://).')
    await waitFor(() => expect(selection(box)).toBe('https://'))
    expect(box).toHaveFocus()
  })

  it('inserts a table as a block of its own', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('Objectives:'))

    const box = await source()
    box.setSelectionRange(11, 11)
    await user.click(screen.getByRole('button', { name: 'Table' }))

    expect(box.value.startsWith('Objectives:\n\n| Column | Column |\n| --- | --- |')).toBe(true)
    expect(within(screen.getByRole('region', { name: 'Preview' })).getByRole('table')).toBeInTheDocument()
  })

  it('answers Ctrl+B, Ctrl+I and Ctrl+K in the source box', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('oil'))

    const box = await source()
    await user.click(box)
    box.setSelectionRange(0, 3)
    await user.keyboard('{Control>}b{/Control}')
    expect(box).toHaveValue('**oil**')

    box.setSelectionRange(2, 5)
    await user.keyboard('{Control>}i{/Control}')
    expect(box).toHaveValue('**_oil_**')

    box.setSelectionRange(3, 6)
    await user.keyboard('{Control>}k{/Control}')
    expect(box).toHaveValue('**_[oil](https://)_**')
  })
})

describe('pictures in a wiki page', () => {
  it('takes a pasted screenshot', async () => {
    const server = withBody('Intro.')
    renderEditor(server)

    const box = await source()
    box.setSelectionRange(6, 6)
    const shot = new File(['png'], 'image.png', { type: 'image/png' })
    fireEvent.paste(box, { clipboardData: { files: [shot] } })

    await waitFor(() => expect(box).toHaveValue('Intro.\n\n![image](/api/media/m-1)\n\n'))
    expect(server.count('POST', '/media')).toBe(1)
  })

  it('leaves pasted text to the textarea', async () => {
    const server = withBody('')
    renderEditor(server)

    const box = await source()
    const pasted = fireEvent.paste(box, { clipboardData: { files: [], getData: () => 'plain words' } })

    /* Not prevented: the browser inserts the text as it always would. */
    expect(pasted).toBe(true)
    expect(server.count('POST', '/media')).toBe(0)
  })

  it('takes a dropped picture', async () => {
    const server = withBody('')
    renderEditor(server)

    const box = await source()
    const file = new File(['png'], 'turret.jpg', { type: 'image/jpeg' })
    fireEvent.drop(box, { dataTransfer: { files: [file] } })

    await waitFor(() => expect(box.value).toContain('![turret](/api/media/m-1)'))
  })

  it('refuses a video in the page body, in words', async () => {
    const server = withBody('')
    renderEditor(server)

    await source()
    const clip = new File(['x'], 'clip.mp4', { type: 'video/mp4' })
    fireEvent.change(screen.getByLabelText('Upload an image'), { target: { files: [clip] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('“clip.mp4” is not a picture')
    expect(server.count('POST', '/media')).toBe(0)
  })

  it('shows the server\'s reason when an image upload is refused', async () => {
    const server = withBody('')
    server.refuseNextUpload('payload_too_large', 'Images must be at most 20 MB.', 413)
    renderEditor(server)

    const box = await source()
    const file = new File(['png'], 'stitch.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload an image'), { target: { files: [file] } })

    expect(await screen.findByRole('alert')).toHaveTextContent('Images must be at most 20 MB.')
    expect(box).toHaveValue('')
  })

  it('sets and removes the hero image', async () => {
    const server = withBody('Text.')
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    const file = new File(['png'], 'hero.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload a hero image'), { target: { files: [file] } })

    await waitFor(() => expect(server.state.pages[0].heroMediaId).toBe('m-1'), { timeout: 4000 })
    expect(document.querySelector('.hero-preview')).toHaveAttribute('src', '/api/media/m-1')

    await user.click(screen.getByRole('button', { name: 'Remove' }))
    await waitFor(() => expect(server.state.pages[0].heroMediaId).toBeNull(), { timeout: 4000 })
  })

  it('lets the author describe the hero image, and saves the description', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ ...DRAFT, body: 'Text.', heroMediaId: 'm-hero' })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    const description = screen.getByLabelText('Describe this image')
    expect(description).toHaveValue('')
    expect(description).toHaveAttribute('maxlength', '1000')

    await user.type(description, 'Two users at the Stellaris 5')

    await waitFor(
      () => expect(server.state.pages[0].heroAlt).toBe('Two users at the Stellaris 5'),
      { timeout: 4000 },
    )
  })

  it('offers no description field while there is no hero to describe', async () => {
    renderEditor(withBody('Text.'))

    await source()

    expect(screen.queryByLabelText('Describe this image')).not.toBeInTheDocument()
  })

  it('does not carry a description over to a different picture', async () => {
    const server = createFakeServer({
      pages: [
        pageFixture({ ...DRAFT, body: 'Text.', heroMediaId: 'm-old', heroAlt: 'The old room' }),
      ],
    })
    renderEditor(server)

    await source()
    expect(screen.getByLabelText('Describe this image')).toHaveValue('The old room')
    const file = new File(['png'], 'hero.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload a hero image'), { target: { files: [file] } })

    await waitFor(() => expect(server.state.pages[0].heroMediaId).toBe('m-1'), { timeout: 4000 })
    expect(server.state.pages[0].heroAlt).toBe('')
    expect(screen.getByLabelText('Describe this image')).toHaveValue('')
  })
})

describe('the two panes', () => {
  it('offers Write and Preview as tabs, with the source showing first', async () => {
    renderEditor(withBody('Use **oil**.'))
    await source()

    const write = screen.getByRole('tab', { name: 'Write' })
    const preview = screen.getByRole('tab', { name: 'Preview' })
    expect(write).toHaveAttribute('aria-selected', 'true')
    expect(preview).toHaveAttribute('aria-selected', 'false')
    expect(document.getElementById(preview.getAttribute('aria-controls') ?? '')).toBe(
      screen.getByRole('region', { name: 'Preview' }),
    )
  })

  it('switches panes, and comes back to the source when a toolbar button is used', async () => {
    const user = userEvent.setup()
    renderEditor(withBody('oil'))

    const box = await source()
    await user.click(screen.getByRole('tab', { name: 'Preview' }))
    expect(screen.getByRole('tab', { name: 'Preview' })).toHaveAttribute('aria-selected', 'true')
    expect(document.querySelector('.wiki-split')).toHaveClass('wiki-split--preview')

    await user.click(screen.getByRole('button', { name: 'Bold' }))

    expect(screen.getByRole('tab', { name: 'Write' })).toHaveAttribute('aria-selected', 'true')
    expect(box).toHaveFocus()
  })

  it('says so when there is nothing to preview', async () => {
    renderEditor(withBody(''))
    await source()

    expect(screen.getByText('Nothing to preview yet.')).toBeInTheDocument()
  })
})

describe('the guide-list dialog', () => {
  it('suggests tags in use and says how many guides the list will hold', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ ...DRAFT, body: '' })],
      guides: [
        guideFixture({ id: 'g1', slug: 'one', tags: ['stellaris', 'confocal'] }),
        guideFixture({ id: 'g2', slug: 'two', tags: ['confocal'] }),
      ],
      tagNames: { stellaris: 'Stellaris', confocal: 'Confocal' },
    })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Insert guide list' }))
    const dialog = screen.getByRole('dialog', { name: 'Insert a guide list' })
    expect(within(dialog).getByRole('button', { name: 'Insert' })).toBeDisabled()

    await user.type(within(dialog).getByLabelText('Add a tag'), 'conf')
    await user.click(await within(dialog).findByRole('option', { name: /Confocal/ }))
    expect(await within(dialog).findByText('2 guides carry this tag right now.')).toBeInTheDocument()

    await user.type(within(dialog).getByLabelText('Add a tag'), 'stell{ArrowDown}{Enter}')
    expect(
      await within(dialog).findByText('1 guide carries all of these tags right now.'),
    ).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Insert' }))
    expect(await source()).toHaveValue('```guidelist\ntags: confocal, stellaris\n```\n\n')
  })

  it('warns before inserting a list that would be empty', async () => {
    const server = createFakeServer({ pages: [pageFixture({ ...DRAFT, body: '' })], guides: [] })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Insert guide list' }))
    const dialog = screen.getByRole('dialog', { name: 'Insert a guide list' })
    await user.type(within(dialog).getByLabelText('Add a tag'), 'cryo{Enter}')

    expect(await within(dialog).findByText(/No guide carries this tag yet/)).toBeInTheDocument()
  })

  it('keeps Escape in the tag suggestions from closing the whole dialog', async () => {
    const server = createFakeServer({
      pages: [pageFixture({ ...DRAFT, body: '' })],
      guides: [guideFixture({ tags: ['confocal'] })],
    })
    const user = userEvent.setup()
    renderEditor(server)

    await source()
    await user.click(screen.getByRole('button', { name: 'Insert guide list' }))
    const dialog = screen.getByRole('dialog', { name: 'Insert a guide list' })
    await user.type(within(dialog).getByLabelText('Add a tag'), 'conf')
    await within(dialog).findByRole('option', { name: /confocal/ })

    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog', { name: 'Insert a guide list' })).toBeInTheDocument()
    expect(within(dialog).queryByRole('option')).not.toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('publishing a page', () => {
  it('drops each reason from the list as it is dealt with', async () => {
    const user = userEvent.setup()
    renderEditor(withBody(''))

    const box = await source()
    await user.click(screen.getByRole('button', { name: 'Publish' }))
    expect(screen.getByText('A page needs some content before it can be published.')).toBeInTheDocument()

    await user.type(box, 'Now there is some.')

    expect(screen.queryByText(/is not ready to publish/)).not.toBeInTheDocument()
  })

  it('shows where a filed page lives in the editor\'s breadcrumb', async () => {
    const server = createFakeServer({
      categories: [categoryFixture()],
      pages: [pageFixture({ ...DRAFT, categoryId: 'c-light' })],
    })
    renderEditor(server)

    await source()
    const crumbs = screen.getByRole('navigation', { name: 'Breadcrumb' })
    expect(within(crumbs).getByRole('link', { name: 'Light Microscopy' })).toHaveAttribute(
      'href',
      '/c/light-microscopy',
    )
    expect(within(crumbs).getByText('Editing page')).toBeInTheDocument()
  })
})

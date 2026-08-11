/**
 * A control that opens a panel beside itself.
 *
 * Deliberately not `role="menu"`: that role promises arrow-key navigation
 * between the items, and these panels hold ordinary links and buttons that Tab
 * already reaches in the right order. Escape closes and hands focus back to the
 * button, because leaving focus on a node that has just been removed drops the
 * next keystroke on `<body>`, at the top of the page.
 *
 * Its own file because two screens wear it: the app header's New and account
 * menus, and the wiki editor's bar — where the `header-menu--up` modifier
 * opens the panel above a control that sits at the foot of the surface.
 */

import { useEffect, useRef, type ReactNode } from 'react'

export function HeaderMenu({
  id,
  className,
  trigger,
  triggerClassName,
  label,
  open,
  onOpen,
  onClose,
  children,
}: {
  id: string
  /** Modifier on the wrapper, which is what decides where the panel appears. */
  className?: string
  trigger: ReactNode
  triggerClassName: string
  /** What a screen reader announces, for a button whose face is a picture. */
  label?: string
  open: boolean
  onOpen: () => void
  onClose: () => void
  children: ReactNode
}) {
  const rootRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return

    /* Anywhere outside the control is somebody asking for the panel to go away. */
    function dismiss(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) onClose()
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape') return
      onClose()
      buttonRef.current?.focus()
    }

    document.addEventListener('mousedown', dismiss)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', dismiss)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, onClose])

  return (
    <div className={`header-menu${className ? ` ${className}` : ''}`} ref={rootRef}>
      <button
        ref={buttonRef}
        type="button"
        className={triggerClassName}
        aria-label={label}
        aria-expanded={open}
        aria-controls={id}
        onClick={() => (open ? onClose() : onOpen())}
      >
        {trigger}
      </button>
      {open && (
        <div className="header-menu__panel" id={id}>
          {children}
        </div>
      )}
    </div>
  )
}

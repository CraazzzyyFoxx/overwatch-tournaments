"use client";

import { X } from "lucide-react";
import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/utils";

/**
 * Every dock on the page shares ONE stack node, appended to `<body>` — the
 * reason this is a portal rather than a plain fixed element in the flow.
 *
 * Docks are mounted by whoever owns the content (the tournament layout owns
 * the broadcast, the pre-game room owns its chat), which is never the same
 * subtree. Two of them anchored to the same corner independently would sit ON
 * each other; a shared flex column stacks them instead, and an open panel
 * pushes the collapsed pills up by its own height with no dock knowing another
 * exists.
 *
 * `flex-col-reverse` puts the first-mounted dock closest to the corner, so the
 * page's own panel does not jump when a second one arrives.
 */
const STACK_ID = "dock-stack";

// Bottom-trailing, inset by the same 1rem the cookie banner uses, with the
// safe-area floor so a panel clears an iOS home indicator. Logical `end`, not
// `right`: the corner follows the writing direction. `z-40` puts the stack
// under the real modals (`ui/dialog`) and under the cookie banner, both `z-50`.
const STACK_CLASS =
  "fixed bottom-4 end-4 z-40 flex flex-col-reverse items-end gap-3 supports-[padding:max(0px)]:mb-[max(0px,env(safe-area-inset-bottom))]";

function dockStack(): HTMLElement {
  const existing = document.getElementById(STACK_ID);
  if (existing !== null) return existing;
  const node = document.createElement("div");
  node.id = STACK_ID;
  node.className = STACK_CLASS;
  document.body.appendChild(node);
  return node;
}

/** The stack node never changes identity, so the store never notifies. */
const NO_UPDATES = () => () => {};
/** No `document` on the server: a dock is page chrome, not SSR content. */
const SERVER_SNAPSHOT = () => null;

export interface DockProps {
  /** Names the landmark and heads the open panel. */
  title: string;
  /** Beside the title, and in the collapsed pill. */
  icon: ReactNode;
  /** `aria-label` of the close control. */
  hideLabel: string;
  /** Collapsed pill text. Defaults to `title`. */
  showLabel?: string;
  /** Trailing node in the collapsed pill — a live dot, a count. */
  badge?: ReactNode;
  /** Controls in the panel header, before the close button. */
  actions?: ReactNode;
  /** Open on mount. A dock that replaced an in-flow panel wants this. */
  defaultOpen?: boolean;
  /** On the panel: its box (width, height, container queries). */
  className?: string;
  children: ReactNode;
}

/**
 * A dismissible panel docked in the bottom-trailing corner, over the page.
 *
 * ## Why a floating dock and not a block in the flow
 *
 * What goes in here — a broadcast, a room chat — is watched or talked to WHILE
 * the page is read. In the flow it costs a band of every screen it appears on
 * and cannot be put away; docked, it costs a corner and the viewer decides.
 *
 * ## Why `<aside>` and not a modal dialog
 *
 * A modal would trap focus and block the page, the opposite of what a corner
 * panel is for. This is a complementary landmark: it announces itself, it is
 * reachable in the landmark list, it takes no focus on arrival, and Escape
 * closes it as a convenience for whoever is already inside it.
 *
 * ## Why hiding unmounts the children
 *
 * "Hide" ends the content rather than parking it behind `display: none` — a
 * viewer who dismissed a live player wants their bandwidth back. Content that
 * must survive a hide (a subscription, a draft message) belongs in the
 * consumer's state, above this component.
 */
export function Dock({
  title,
  icon,
  hideLabel,
  showLabel,
  badge,
  actions,
  defaultOpen = false,
  className,
  children
}: Readonly<DockProps>) {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  // `useSyncExternalStore` rather than a mount effect: React reads the SERVER
  // snapshot while hydrating and only then the client one, so the stack node
  // is appended to <body> after hydration — creating it during the hydration
  // render would shift the children React is matching by position. The store
  // never changes, hence the no-op subscribe.
  const stack = useSyncExternalStore(NO_UPDATES, dockStack, SERVER_SNAPSHOT);
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreRef = useRef<HTMLButtonElement>(null);
  // Both controls unmount the moment they are used, so focus would fall to
  // <body> and a keyboard user would restart their traversal from the top of
  // the document. The ref gates the effect to USER toggles: without it, the
  // dock would steal focus from the page on first render.
  const shouldMoveFocus = useRef(false);
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!shouldMoveFocus.current) {
      return;
    }
    shouldMoveFocus.current = false;
    (isOpen ? closeRef : restoreRef).current?.focus();
  }, [isOpen]);

  // A native listener on the panel, not React's `onKeyDown`: the panel is
  // portalled to <body>, and React delegates events to the root container it
  // was mounted into — which the portal sits outside of whenever that root is
  // anything narrower than the document. Bound to the node itself, so this is
  // Escape from INSIDE the panel and nothing else on the page.
  useEffect(() => {
    const node = panelRef.current;
    if (node === null) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      shouldMoveFocus.current = true;
      setIsOpen(false);
    };
    node.addEventListener("keydown", onEscape);
    return () => node.removeEventListener("keydown", onEscape);
  }, [isOpen]);

  if (stack === null) return null;

  const toggle = (next: boolean) => {
    shouldMoveFocus.current = true;
    setIsOpen(next);
  };

  if (!isOpen) {
    return createPortal(
      <button
        ref={restoreRef}
        type="button"
        onClick={() => toggle(true)}
        className="inline-flex items-center gap-2 rounded-full border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-card)]/95 px-3.5 py-2.5 text-caption font-semibold text-[color:var(--aqt-fg)] shadow-xl backdrop-blur outline-none transition-colors hover:border-[color:var(--aqt-teal)] hover:text-[color:var(--aqt-teal)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
      >
        <span className="text-[color:var(--aqt-teal)]">{icon}</span>
        {showLabel ?? title}
        {badge}
      </button>,
      stack
    );
  }

  return createPortal(
    <aside
      ref={panelRef}
      aria-label={title}
      className={cn(
        "flex w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)]/95 shadow-2xl backdrop-blur",
        className
      )}
    >
      {/* Not `.aqt-card-head`: its 14/18 padding and single line eat a panel
          this narrow. Same vocabulary (title font, bottom rule), tighter box.
          The close control is pinned to the corner rather than laid out in the
          row, so it stays where a viewer looks for it and cannot be pushed off
          by a long heading; the row reserves its width with `pe-11` and wraps
          under it if it must. */}
      <div className="relative flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b border-[color:var(--aqt-border)] py-2.5 pe-11 ps-3">
        <h2 className="aqt-card-title min-w-0 flex-1">
          <span className="aqt-card-title-ic">{icon}</span>
          <span className="truncate">{title}</span>
        </h2>
        {actions}
        <button
          ref={closeRef}
          type="button"
          onClick={() => toggle(false)}
          aria-label={hideLabel}
          // 32px square: over the WCAG 2.5.8 24px floor without turning the
          // header into a toolbar.
          className="absolute end-2 top-2 inline-flex size-8 shrink-0 items-center justify-center rounded-[8px] text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {children}
    </aside>,
    stack
  );
}

export default Dock;

// @vitest-environment happy-dom
//
// The row detail surface for every T2 browser. What is pinned here:
//  1. `openId === null` renders nothing — the inspector is URL state, not a
//     mounted-but-hidden panel;
//  2. on a wide viewport it is a PANEL beside the table, not an overlay, so
//     the rows stay visible while a row is investigated (F2 ·5);
//  3. below `lg` the same content becomes a full-screen sheet;
//  4. Esc closes, and ↑/↓ page through rows — but never while the caret is in
//     a field inside the inspector;
//  5. `openHref` is the only thing that renders "Open page", because not every
//     entity has a route.
import { act, forwardRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Inspector } from "@/components/kit/Inspector";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; children: React.ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, ...props }, ref) {
    return (
      <a ref={ref} href={href} {...props}>
        {children}
      </a>
    );
  })
}));

let container: HTMLElement;
let root: Root;
const onClose = vi.fn();
const onPrev = vi.fn();
const onNext = vi.fn();

function mockViewport(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: wide,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

function inspector(props: Partial<React.ComponentProps<typeof Inspector>>) {
  return (
    <Inspector
      openId="8812"
      onClose={onClose}
      title="Encounter #8812"
      subtitle="Anak Cup #14 · Groups · Round 3"
      onPrev={onPrev}
      onNext={onNext}
      {...props}
    >
      <p>Team C vs Team D</p>
      <input aria-label="Note" />
    </Inspector>
  );
}

async function render(
  props: Partial<React.ComponentProps<typeof Inspector>> = {},
  wide = true
) {
  mockViewport(wide);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(inspector(props));
  });
}

async function rerender(props: Partial<React.ComponentProps<typeof Inspector>>) {
  await act(async () => {
    root.render(inspector(props));
  });
}

async function keyDown(key: string, target: EventTarget = document) {
  await act(async () => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

beforeEach(() => {
  onClose.mockClear();
  onPrev.mockClear();
  onNext.mockClear();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("Inspector", () => {
  it("renders nothing when no row is open", async () => {
    await render({ openId: null });

    expect(document.body.textContent).not.toContain("Encounter #8812");
  });

  it("is a panel inside the content on a wide viewport", async () => {
    await render();

    const panel = document.querySelector('[data-inspector-mode="panel"]');
    expect(panel).not.toBeNull();
    expect(panel?.tagName).toBe("ASIDE");
    expect(panel?.textContent).toContain("Team C vs Team D");
  });

  // The row that opened the panel is handed focus back on CLOSE only. Doing it
  // on every `openId` change scrolled the page to that first row — from row 500
  // of a long table, a jump back to the top on every click.
  it("hands focus back to the opening row on close, not on every row switch", async () => {
    const row = document.createElement("button");
    document.body.appendChild(row);
    row.focus();

    await render();
    const rowFocus = vi.spyOn(row, "focus");

    await rerender({ openId: "8813", title: "Encounter #8813" });
    expect(rowFocus).not.toHaveBeenCalled();

    await rerender({ openId: null });
    expect(rowFocus).toHaveBeenCalledTimes(1);
  });

  it("becomes a sheet below lg", async () => {
    await render({}, false);

    expect(document.querySelector('[data-inspector-mode="panel"]')).toBeNull();
    expect(document.querySelector("[role='dialog']")?.textContent).toContain("Team C vs Team D");
  });

  it("closes on Escape", async () => {
    await render();

    await keyDown("Escape");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("pages rows with the arrow keys", async () => {
    await render();

    await keyDown("ArrowDown");
    await keyDown("ArrowUp");
    expect(onNext).toHaveBeenCalledTimes(1);
    expect(onPrev).toHaveBeenCalledTimes(1);
  });

  it("leaves the arrow keys to a field inside it", async () => {
    await render();
    const field = document.querySelector<HTMLInputElement>('input[aria-label="Note"]');

    await keyDown("ArrowDown", field!);
    expect(onNext).not.toHaveBeenCalled();
  });

  // The notes sheet and the image viewer open over the inspector: Esc there closed the inspector
  // under them too, and ↑/↓ switched the row, unmounting the very dialog being used.
  it("leaves Escape and the arrow keys to a dialog opened over it", async () => {
    await render();
    const dialog = document.body.appendChild(document.createElement("div"));
    dialog.setAttribute("role", "dialog");
    const button = dialog.appendChild(document.createElement("button"));

    await keyDown("Escape", button);
    await keyDown("ArrowDown", button);
    expect(onClose).not.toHaveBeenCalled();
    expect(onNext).not.toHaveBeenCalled();
  });

  it("still closes on Escape from inside its own sheet below lg", async () => {
    await render({}, false);
    const field = document.querySelector<HTMLInputElement>('input[aria-label="Note"]');

    await keyDown("Escape", field!);
    expect(onClose).toHaveBeenCalled();
  });

  it("offers Open page only when the entity has a route", async () => {
    await render();
    expect(document.body.textContent).not.toContain("Open page");

    await act(async () => {
      root.unmount();
    });
    container.remove();
    await render({ openHref: "/admin/tournaments/14/matches/encounters" });

    const link = [...document.querySelectorAll("a")].find((anchor) =>
      anchor.textContent?.includes("Open page")
    );
    expect(link?.getAttribute("href")).toBe("/admin/tournaments/14/matches/encounters");
  });

  it("names its controls for assistive technology", async () => {
    await render();

    const labels = [...document.querySelectorAll("button")].map((button) =>
      button.getAttribute("aria-label")
    );
    expect(labels).toContain("Previous row");
    expect(labels).toContain("Next row");
    expect(labels).toContain("Close inspector");
  });

  it("resizes from its left edge by keyboard within bounds, remembers the width, and resets on double-click", async () => {
    localStorage.removeItem("admin-inspector-width");
    await render();
    const panel = () => document.querySelector<HTMLElement>('[data-inspector-mode="panel"]')!;
    const handle = document.querySelector<HTMLElement>('[role="separator"][aria-label="Resize inspector"]')!;

    expect(panel().style.width).toBe("380px");
    await keyDown("ArrowLeft", handle);
    expect(panel().style.width).toBe("396px");
    expect(localStorage.getItem("admin-inspector-width")).toBe("396");

    for (let step = 0; step < 40; step += 1) await keyDown("ArrowLeft", handle);
    expect(handle.getAttribute("aria-valuenow")).toBe("720");

    await act(async () => {
      handle.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
    });
    expect(panel().style.width).toBe("380px");
  });
});

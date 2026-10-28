// @vitest-environment happy-dom
import { act, useRef, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { ImperativePanelHandle } from "react-resizable-panels";

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function nextTick(): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(node);
  });
  // react-resizable-panels registers each Panel in a layout effect and only
  // computes the group's initial flex-grow layout once every panel has
  // registered; that settles one tick after the render commit, so imperative
  // calls (`collapse()`/keyboard resize) issued in the same tick as mount
  // would otherwise race a not-yet-populated layout.
  await act(async () => {
    await nextTick();
  });
  return container;
}

function panelSize(scope: HTMLElement, panelId: string): number {
  const panel = scope.querySelector(`[data-panel-id="${panelId}"]`);
  return Number(panel?.getAttribute("data-panel-size"));
}

function Harness({ onCollapse, onExpand }: { onCollapse: () => void; onExpand: () => void }) {
  const sidebarRef = useRef<ImperativePanelHandle>(null);

  return (
    <div>
      <button type="button" onClick={() => sidebarRef.current?.collapse()}>
        collapse
      </button>
      <button type="button" onClick={() => sidebarRef.current?.expand()}>
        expand
      </button>
      <ResizablePanelGroup direction="horizontal">
        <ResizablePanel
          ref={sidebarRef}
          id="sidebar"
          defaultSize={30}
          minSize={20}
          maxSize={50}
          collapsible
          collapsedSize={5}
          onCollapse={onCollapse}
          onExpand={onExpand}
        >
          sidebar-content
        </ResizablePanel>
        <ResizableHandle withHandle />
        <ResizablePanel id="content" minSize={40}>
          main-content
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

describe("Resizable", () => {
  it("renders both panels split by a keyboard-focusable separator", async () => {
    const scope = await mount(<Harness onCollapse={() => {}} onExpand={() => {}} />);

    expect(scope.textContent).toContain("sidebar-content");
    expect(scope.textContent).toContain("main-content");

    const handle = scope.querySelector("[role='separator']");
    expect(handle).not.toBeNull();
    expect(handle?.getAttribute("tabIndex")).toBe("0");
  });

  it("grows the sidebar panel when the handle is resized with the arrow keys", async () => {
    const scope = await mount(<Harness onCollapse={() => {}} onExpand={() => {}} />);
    const handle = scope.querySelector<HTMLElement>("[role='separator']");
    expect(handle).not.toBeNull();

    const initialSize = panelSize(scope, "sidebar");

    await act(async () => {
      // The handle tracks its focus in state, so focusing it is an update too.
      handle?.focus();
      handle?.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });

    // Dragging the divider right hands the sidebar panel more of the group's
    // flex-grow share — the actual "narrow/widen dynamically" contract.
    expect(panelSize(scope, "sidebar")).toBeGreaterThan(initialSize);
  });

  it("collapses and re-expands the sidebar panel imperatively, like the pool sidebar's toggle button", async () => {
    const onCollapse = vi.fn();
    const onExpand = vi.fn();
    const scope = await mount(<Harness onCollapse={onCollapse} onExpand={onExpand} />);
    const buttons = [...scope.querySelectorAll("button")];
    const collapseButton = buttons.find((button) => button.textContent === "collapse");
    const expandButton = buttons.find((button) => button.textContent === "expand");

    await act(async () => {
      collapseButton?.click();
    });
    expect(onCollapse).toHaveBeenCalledTimes(1);
    expect(panelSize(scope, "sidebar")).toBeCloseTo(5, 1);

    await act(async () => {
      expandButton?.click();
    });
    // react-resizable-panels' `expand()` can re-fire `onExpand` once more
    // while it re-clamps the panel back above `minSize`; the call itself
    // (not a fixed count) is the contract that keeps `isPoolSidebarCollapsed`
    // in sync with the real panel state.
    expect(onExpand).toHaveBeenCalled();
    expect(panelSize(scope, "sidebar")).toBeCloseTo(30, 1);
  });
});

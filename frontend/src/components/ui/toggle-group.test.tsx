// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(node);
  });
  return container;
}

function radios(scope: HTMLElement) {
  return [...scope.querySelectorAll<HTMLButtonElement>("[role='radio']")];
}

function group(value: string, onValueChange: (next: string) => void) {
  return (
    <ToggleGroup value={value} onValueChange={onValueChange} aria-label="Filter by status">
      <ToggleGroupItem value="all">All</ToggleGroupItem>
      <ToggleGroupItem value="failed">Failed</ToggleGroupItem>
      <ToggleGroupItem value="done">Processed</ToggleGroupItem>
    </ToggleGroup>
  );
}

describe("ToggleGroup", () => {
  it("exposes a labelled radiogroup", async () => {
    const scope = await mount(group("all", () => {}));

    const container = scope.querySelector("[role='radiogroup']");
    expect(container).not.toBeNull();
    // The label used to be dropped: TypeScript allows any hyphenated JSX
    // attribute, so `aria-label` silently went nowhere.
    expect(container?.getAttribute("aria-label")).toBe("Filter by status");
  });

  it("keeps one tab stop on the selected segment", async () => {
    const scope = await mount(group("failed", () => {}));

    expect(radios(scope).map((item) => item.tabIndex)).toEqual([-1, 0, -1]);
  });

  it("moves and selects with arrow keys, wrapping at the ends", async () => {
    const onValueChange = vi.fn();
    const scope = await mount(group("all", onValueChange));

    const items = radios(scope);
    items[0].focus();
    await act(async () => {
      items[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
    });
    expect(onValueChange).toHaveBeenLastCalledWith("failed");
    expect(document.activeElement).toBe(items[1]);

    await act(async () => {
      items[1].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }));
    });
    expect(onValueChange).toHaveBeenLastCalledWith("all");
  });

  it("keeps one tab stop, on the first option, when nothing is selected", async () => {
    const scope = await mount(group("", () => {}));

    expect(radios(scope).map((item) => item.tabIndex)).toEqual([0, -1, -1]);
  });

  it("works under a TooltipTrigger asChild: keeps its on state and still selects", async () => {
    const onValueChange = vi.fn();
    const scope = await mount(
      <TooltipProvider>
        <ToggleGroup value="all" onValueChange={onValueChange} aria-label="View">
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          <Tooltip>
            <TooltipTrigger asChild>
              <ToggleGroupItem value="failed">Failed</ToggleGroupItem>
            </TooltipTrigger>
            <TooltipContent>Only the failed ones</TooltipContent>
          </Tooltip>
        </ToggleGroup>
      </TooltipProvider>
    );

    const [, failed] = radios(scope);
    expect(failed.getAttribute("data-state")).toBe("off");
    await act(async () => {
      failed.click();
    });
    expect(onValueChange).toHaveBeenLastCalledWith("failed");
  });
});

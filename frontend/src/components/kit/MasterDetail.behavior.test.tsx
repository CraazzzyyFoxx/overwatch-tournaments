// @vitest-environment happy-dom
//
// The T4 layout. What is pinned here:
//  1. with nothing selected the detail column shows `emptyDetail`, and the
//     narrow layout stays on the list;
//  2. with a selection the detail is rendered and the narrow layout offers a
//     way back — the list is hidden below `md`, so without it a phone user is
//     trapped in the editor;
//  3. `listWidth` drives the grid, so a roles list and a stages list can have
//     different rails without either page writing a grid by hand.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MasterDetail } from "@/components/kit/MasterDetail";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

async function render(props: Partial<React.ComponentProps<typeof MasterDetail>> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MasterDetail
        list={<p>Stage 1 · Groups</p>}
        detail={null}
        emptyDetail={<p>Pick a stage</p>}
        {...props}
      />
    );
  });
}

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("MasterDetail", () => {
  it("shows the empty detail and keeps the list visible with no selection", async () => {
    await render();

    expect(container.textContent).toContain("Pick a stage");
    expect(container.textContent).toContain("Stage 1 · Groups");
    // The list column is not the one collapsed below md.
    const columns = container.firstElementChild!.children;
    expect(columns[0].className).not.toContain("hidden");
  });

  it("renders the detail and a way back when a row is selected", async () => {
    await render({ detail: <p>Stage 2 editor</p> });

    expect(container.textContent).toContain("Stage 2 editor");
    expect(container.textContent).not.toContain("Pick a stage");

    const back = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Back to list")
    );
    expect(back).toBeDefined();

    const historyBack = vi.spyOn(window.history, "back").mockImplementation(() => undefined);
    await act(async () => {
      back?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(historyBack).toHaveBeenCalledTimes(1);
    historyBack.mockRestore();
  });

  it("drives the grid from listWidth", async () => {
    await render({ listWidth: 340 });

    expect(container.firstElementChild?.getAttribute("style")).toContain("340px");
  });
});

// @vitest-environment happy-dom
//
// The lifecycle indicator. What is pinned here:
//  1. exactly one phase carries `aria-current="step"`;
//  2. it renders NO interactive element — advancing a phase has consequences
//     and belongs to an explicit action, not to a progress bar;
//  3. the connector rules between phases are decoration and stay hidden from
//     assistive technology.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { PhaseStrip } from "@/components/kit/PhaseStrip";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <PhaseStrip
        phases={[
          { key: "setup", label: "Setup", state: "done" },
          { key: "ready", label: "Ready", state: "current" },
          { key: "live", label: "Live", state: "todo" },
          { key: "done", label: "Done", state: "todo" }
        ]}
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

describe("PhaseStrip", () => {
  it("marks exactly the current phase", async () => {
    await render();

    const current = container.querySelectorAll('[aria-current="step"]');
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("Ready");
  });

  it("lists the phases in order", async () => {
    await render();

    expect(container.querySelector("ol")?.getAttribute("aria-label")).toBe("Phases");
    const labels = [...container.querySelectorAll("ol > li")].map((item) =>
      item.textContent?.trim()
    );
    expect(labels).toEqual(["Setup", "Ready", "Live", "Done"]);
  });

  it("offers nothing to click", async () => {
    await render();

    expect(container.querySelectorAll("button, a")).toHaveLength(0);
  });
});

// @vitest-environment happy-dom
//
// The T6 wizard frame. What is pinned here:
//  1. the current step is the only one carrying `aria-current="step"`;
//  2. a `skipped` step keeps its place in the rail but takes NO number, so
//     skipping "Conflicts" does not renumber the steps after it;
//  3. the rail is an ordered list (a wizard's order is the information);
//  4. the footer's Next honours `disabled` and never fires when blocked.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WizardShell, type WizardStep } from "@/components/kit/WizardShell";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const STEPS: WizardStep[] = [
  { key: "source", label: "Source", state: "done" },
  { key: "grid", label: "Grid & version", state: "current" },
  { key: "conflicts", label: "Conflicts", state: "skipped" },
  { key: "draft", label: "Create draft", state: "todo" }
];

const onNext = vi.fn();
const onBack = vi.fn();
let container: HTMLElement;
let root: Root;

async function render(props: Partial<React.ComponentProps<typeof WizardShell>> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <WizardShell
        steps={STEPS}
        footer={{ back: onBack, next: { label: "Continue", onClick: onNext } }}
        aside={<p>Import from Challonge instead</p>}
        {...props}
      >
        <p>Pick a grid</p>
      </WizardShell>
    );
  });
}

function button(label: string) {
  return [...container.querySelectorAll("button")].find((candidate) =>
    candidate.textContent?.trim().includes(label)
  );
}

async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

beforeEach(() => {
  onNext.mockClear();
  onBack.mockClear();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("WizardShell", () => {
  it("renders the rail as an ordered list with one current step", async () => {
    await render();

    expect(container.querySelector("ol")?.getAttribute("aria-label")).toBe("Steps");
    const current = container.querySelectorAll('[aria-current="step"]');
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("Grid & version");
  });

  it("gives a skipped step no number and does not renumber the rest", async () => {
    await render();

    const items = [...container.querySelectorAll("ol > li")];
    const numbers = items.map((item) => item.querySelector("span")?.textContent?.trim());
    // Step 1 is done (a check, not a number); "Conflicts" is skipped (blank);
    // "Create draft" keeps 3, the position it would have had.
    expect(numbers[2]).toBe("");
    expect(numbers[3]).toBe("3");
  });

  it("renders the content and the aside slot", async () => {
    await render();

    expect(container.textContent).toContain("Pick a grid");
    expect(container.textContent).toContain("Import from Challonge instead");
  });

  it("wires the footer buttons", async () => {
    await render();

    await click(button("Back"));
    await click(button("Continue"));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("blocks a disabled Next", async () => {
    await render({
      footer: { next: { label: "Continue", onClick: onNext, disabled: true } }
    });

    expect(button("Continue")?.disabled).toBe(true);
    await click(button("Continue"));
    expect(onNext).not.toHaveBeenCalled();
  });
});

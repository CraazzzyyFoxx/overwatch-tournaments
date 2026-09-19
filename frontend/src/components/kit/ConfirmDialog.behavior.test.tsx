// @vitest-environment happy-dom
//
// The single confirmation surface. What is pinned here:
//  1. one instance renders whichever `intent` it is handed, which is what lets
//     a screen with six destructive operations mount one dialog instead of six;
//  2. `requireTyped` keeps the action disabled until the exact string is typed,
//     and a reopen does not carry the previous answer over;
//  3. `cascade` lists what else disappears;
//  4. `pending` disables both buttons so a double-confirm cannot fire twice.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog, type ConfirmIntent } from "@/components/kit/ConfirmDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const DELETE_STAGE: ConfirmIntent = {
  title: "Delete stage",
  description: "Stage 2 · Playoffs is removed.",
  confirmLabel: "Delete stage",
  tone: "danger",
  cascade: ["12 encounters", "2 standings rows"]
};

const onConfirm = vi.fn();
let container: HTMLElement;
let root: Root;

async function render(
  props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}
) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <ConfirmDialog
        open
        onOpenChange={() => undefined}
        intent={DELETE_STAGE}
        onConfirm={onConfirm}
        {...props}
      />
    );
  });
}

function button(label: string) {
  return [...document.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === label
  );
}

async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

/** React tracks the input's value on the DOM node, so assigning `.value`
 *  directly is invisible to it — go through the native setter. */
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  onConfirm.mockClear();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("ConfirmDialog", () => {
  it("renders the intent's title, description and cascade", async () => {
    await render();

    const dialog = document.querySelector("[role='alertdialog']");
    expect(dialog?.textContent).toContain("Delete stage");
    expect(dialog?.textContent).toContain("Stage 2 · Playoffs is removed.");
    expect(dialog?.textContent).toContain("12 encounters");
  });

  it("confirms on the action button", async () => {
    await render();

    await click(button("Delete stage"));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("keeps the action disabled until the required name is typed", async () => {
    await render({
      intent: {
        title: "Delete tournament",
        description: "This cannot be undone.",
        confirmLabel: "Delete tournament",
        tone: "danger",
        requireTyped: "Anak Cup #14"
      }
    });

    const action = button("Delete tournament");
    expect(action?.disabled).toBe(true);

    await type(document.querySelector<HTMLInputElement>("input")!, "Anak Cup #14");

    expect(button("Delete tournament")?.disabled).toBe(false);
  });

  it("blocks both buttons while the action is in flight", async () => {
    await render({ pending: true });

    expect(button("Delete stage")?.disabled).toBe(true);
    expect(button("Cancel")?.disabled).toBe(true);
  });

  it("swaps the whole intent on the same instance", async () => {
    await render();

    await act(async () => {
      root.render(
        <ConfirmDialog
          open
          onOpenChange={() => undefined}
          intent={{
            title: "Merge stages",
            description: "Group stages are merged into one.",
            confirmLabel: "Merge stages",
            tone: "warning"
          }}
          onConfirm={onConfirm}
        />
      );
    });

    const dialog = document.querySelector("[role='alertdialog']");
    expect(dialog?.textContent).toContain("Merge stages");
    expect(dialog?.textContent).not.toContain("12 encounters");
  });
});

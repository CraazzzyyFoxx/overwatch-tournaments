// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { InlineEditText } from "@/components/kit/InlineEditText";

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

function button(scope: HTMLElement, label: string) {
  return scope.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);
}

function input(scope: HTMLElement) {
  return scope.querySelector<HTMLInputElement>('input[aria-label="group name"]');
}

async function click(element: HTMLElement | null) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}
// React overrides the input's own `value` setter to track changes; assigning through it
// makes React think nothing changed, so write via the prototype setter instead.
const nativeValueSetter = Object.getOwnPropertyDescriptor(
  HTMLInputElement.prototype,
  "value"
)?.set;

async function typeInto(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("InlineEditText", () => {
  it("renames through pencil -> input -> save", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const scope = await mount(
      <InlineEditText value="Group 1" label="group name" onSave={onSave} />
    );

    expect(scope.textContent).toContain("Group 1");
    await click(button(scope, "Edit group name"));

    const field = input(scope);
    expect(field?.value).toBe("Group 1");
    await typeInto(field!, "  Group A  ");
    await click(button(scope, "Save group name"));

    expect(onSave).toHaveBeenCalledWith("Group A");
    expect(input(scope)).toBeNull();
  });

  it("keeps the draft when saving fails and drops it on cancel", async () => {
    const onSave = vi.fn().mockRejectedValue(new Error("boom"));
    const scope = await mount(
      <InlineEditText value="Group 1" label="group name" onSave={onSave} />
    );

    await click(button(scope, "Edit group name"));
    await typeInto(input(scope)!, "Group B");
    await click(button(scope, "Save group name"));

    expect(input(scope)?.value).toBe("Group B");

    await click(button(scope, "Cancel group name edit"));
    expect(input(scope)).toBeNull();
  });

  it("skips the save call when the name is unchanged", async () => {
    const onSave = vi.fn();
    const scope = await mount(
      <InlineEditText value="Group 1" label="group name" onSave={onSave} />
    );

    await click(button(scope, "Edit group name"));
    await click(button(scope, "Save group name"));

    expect(onSave).not.toHaveBeenCalled();
    expect(input(scope)).toBeNull();
  });

  it("hides the pencil when editing is not allowed", async () => {
    const scope = await mount(
      <InlineEditText value="Group 1" label="group name" canEdit={false} onSave={() => {}} />
    );
    expect(button(scope, "Edit group name")).toBeNull();
  });
});

// @vitest-environment happy-dom
//
// The save affordance for every T5 settings section. What is pinned here:
//  1. nothing renders while the form is clean — a permanent disabled "Save"
//     teaches the reader nothing;
//  2. it appears with the dirty summary and both actions once edits exist;
//  3. `saving` blocks both buttons, so a double-click cannot save twice;
//  4. an in-app link click while dirty is intercepted and routed through the
//     discard prompt instead of losing the edits silently;
//  5. `guardNavigation={false}` turns that interception off, for a screen
//     whose routed sub-navigation is part of the same form.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { NextIntlClientProvider } from "next-intl";

import en from "@/i18n/messages/en.json";
import { SaveBar } from "@/components/kit/SaveBar";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push })
}));

const onSave = vi.fn();
const onDiscard = vi.fn();
let container: HTMLElement;
let root: Root;

async function render(props: Partial<React.ComponentProps<typeof SaveBar>> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <a href="/admin/settings/branding">Branding</a>
        <SaveBar
          dirty
          summary="3 changed fields"
          onSave={onSave}
          onDiscard={onDiscard}
          {...props}
        />
      </NextIntlClientProvider>
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

beforeEach(() => {
  push.mockClear();
  onSave.mockClear();
  onDiscard.mockClear();
  window.history.replaceState(null, "", "/admin/settings/general");
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("SaveBar", () => {
  it("renders nothing while the form is clean", async () => {
    await render({ dirty: false });

    expect(container.querySelector("[role='region']")).toBeNull();
  });

  it("shows the dirty summary and both actions", async () => {
    await render();

    const region = container.querySelector("[role='region']");
    expect(region?.getAttribute("aria-label")).toBe("Unsaved changes");
    expect(region?.textContent).toContain("3 changed fields");

    await click(button("Save changes"));
    expect(onSave).toHaveBeenCalledTimes(1);

    await click(button("Discard"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });

  it("blocks both actions while saving", async () => {
    await render({ saving: true });

    expect(button("Discard")?.disabled).toBe(true);
    expect(container.querySelector("[role='region'] button:last-of-type")).toHaveProperty(
      "disabled",
      true
    );
  });

  it("routes an in-app link click through the discard prompt", async () => {
    await render();

    await click(document.querySelector('a[href="/admin/settings/branding"]'));

    // The navigation is held, not performed.
    expect(push).not.toHaveBeenCalled();
    expect(document.querySelector("[role='alertdialog']")?.textContent).toContain(
      "Discard unsaved changes?"
    );

    await click(button("Discard changes"));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(push).toHaveBeenCalledWith("/admin/settings/branding");
  });

  it("lets a link through when the screen's sub-navigation is part of the form", async () => {
    await render({ guardNavigation: false });

    await click(document.querySelector('a[href="/admin/settings/branding"]'));

    // No prompt and no held href: `?section=` links inside one editor do not
    // unmount it, so there is nothing to discard.
    expect(document.querySelector("[role='alertdialog']")).toBeNull();
    expect(onDiscard).not.toHaveBeenCalled();
    // The bar itself is untouched — this only turns off the anchor guard.
    expect(container.querySelector("[role='region']")).not.toBeNull();
  });
});

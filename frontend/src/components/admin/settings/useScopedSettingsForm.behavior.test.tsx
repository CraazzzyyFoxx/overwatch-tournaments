// @vitest-environment happy-dom
//
// The one branch every settings section inherits from this hook: what happens
// when the saved entity changes under an open editor. What is pinned here:
//  1. a refetch that arrives while nothing is unsaved adopts the new values —
//     otherwise another admin's write stays invisible until a reload;
//  2. a refetch that arrives mid-edit keeps the typing. Re-baselining is not
//     allowed to throw away what the user has not saved yet;
//  3. no render in between ever reports a phantom changed field. The baseline
//     is derived during render, so re-baselining in an effect would commit one
//     render comparing the NEW baseline against the OLD form and flash a save
//     bar for an edit nobody made.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useScopedSettingsForm } from "./useScopedSettingsForm";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

interface Form {
  name: string;
}

let container: HTMLDivElement;
let root: Root;
/** Every render's summary, so a one-render flash is observable. */
let summaries: string[];

function Section({ baseline }: Readonly<{ baseline: Form }>) {
  const settings = useScopedSettingsForm<Form, Partial<Form>>({
    baseline,
    toPayload: (form, base) => (form.name === base.name ? {} : { name: form.name }),
    submit: async () => undefined
  });
  summaries.push(settings.summary);

  return (
    <div>
      <input
        id="name"
        value={settings.form?.name ?? ""}
        onChange={(event) => settings.patch({ name: event.target.value })}
      />
      <span id="dirty">{settings.dirty ? settings.summary : "clean"}</span>
    </div>
  );
}

async function render(baseline: Form) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <Section baseline={baseline} />
      </QueryClientProvider>
    );
  });
}

/** Type into a controlled input the way React's synthetic layer sees it. */
async function type(value: string) {
  const input = container.querySelector<HTMLInputElement>("#name")!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  summaries = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("useScopedSettingsForm › re-baseline", () => {
  it("adopts a refetched entity while the form is clean, without flashing changes", async () => {
    await render({ name: "OWT 64" });
    await render({ name: "OWT 65" });

    expect(container.querySelector<HTMLInputElement>("#name")?.value).toBe("OWT 65");
    expect(container.querySelector("#dirty")?.textContent).toBe("clean");
    expect(summaries.every((summary) => summary === "0 changed fields")).toBe(true);
  });

  it("keeps unsaved typing when the entity changes under the editor", async () => {
    await render({ name: "OWT 64" });
    await type("OWT 64 Redux");
    await render({ name: "OWT 65" });

    expect(container.querySelector<HTMLInputElement>("#name")?.value).toBe("OWT 64 Redux");
    // Still dirty, and now against the refetched baseline: the save sends the
    // user's value, not a diff against values the server has already moved on
    // from.
    expect(container.querySelector("#dirty")?.textContent).toBe("1 changed field");
  });
});

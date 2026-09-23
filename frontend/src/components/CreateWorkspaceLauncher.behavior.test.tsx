// @vitest-environment happy-dom
//
// The only workspace-creation surface a plain account can reach. `/admin/*`
// refuses anyone who administers nothing, so if this button stops working the
// self-service feature has no entry point at all. What is pinned here:
//  1. an anonymous visitor gets the sign-in modal, not a doomed POST;
//  2. a signed-in one gets the shared dialog, and submitting it creates the
//     workspace and lands on its settings;
//  3. the two refusals self-service added read as instructions — the raw
//     `workspace_create_limit_reached` code must never reach a human.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateWorkspaceLauncher } from "@/components/CreateWorkspaceLauncher";
import { ApiError } from "@/lib/api/error";
import en from "@/i18n/messages/en.json";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const create = vi.fn();
const uploadIcon = vi.fn();
const openAuthModal = vi.fn();
const push = vi.fn();
const fetchWorkspaces = vi.fn();

let user: { id: number } | null = { id: 4 };

vi.mock("@/services/workspace.service", () => ({
  default: {
    create: (...args: unknown[]) => create(...args),
    uploadIcon: (...args: unknown[]) => uploadIcon(...args)
  }
}));
vi.mock("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => ({ user }) }));
vi.mock("@/stores/auth-modal.store", () => ({
  useAuthModalStore: (selector: (state: { open: () => void }) => unknown) =>
    selector({ open: openAuthModal })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { fetchWorkspaces: () => void }) => unknown) =>
    selector({ fetchWorkspaces })
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

let container: HTMLDivElement;
let root: Root;

async function settle(times = 4) {
  for (let turn = 0; turn < times; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
        >
          <CreateWorkspaceLauncher />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

async function click(node: Element | null | undefined) {
  expect(node).toBeTruthy();
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

async function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    globalThis.HTMLInputElement.prototype,
    "value"
  )?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

async function openDialog() {
  await click(container.querySelector("button"));
  const dialog = document.querySelector('[role="dialog"]');
  expect(dialog).toBeTruthy();
  return dialog as HTMLElement;
}

async function submit(dialog: HTMLElement, slug = "rivals", name = "Rivals Cup") {
  await type(dialog.querySelector("#slug") as HTMLInputElement, slug);
  await type(dialog.querySelector("#name") as HTMLInputElement, name);
  await act(async () => {
    dialog.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

beforeEach(() => {
  user = { id: 4 };
  create.mockReset().mockResolvedValue({ id: 12, slug: "rivals", name: "Rivals Cup" });
  uploadIcon.mockReset();
  openAuthModal.mockReset();
  push.mockReset();
  fetchWorkspaces.mockReset();
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Create workspace launcher", () => {
  it("asks an anonymous visitor to sign in instead of posting", async () => {
    user = null;
    await render();

    await click(container.querySelector("button"));

    expect(openAuthModal).toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(create).not.toHaveBeenCalled();
  });

  it("creates the workspace and lands on its settings", async () => {
    await render();
    await submit(await openDialog());

    expect(create).toHaveBeenCalledWith({
      slug: "rivals",
      name: "Rivals Cup",
      description: undefined
    });
    expect(push).toHaveBeenCalledWith("/admin/workspaces/12/general");
  });

  it("turns the ownership cap into an instruction, not a machine code", async () => {
    create.mockRejectedValue(
      new ApiError(403, [{ msg: "workspace_create_limit_reached", code: "error" }])
    );
    await render();
    const dialog = await openDialog();
    await submit(dialog);

    expect(dialog.textContent).toContain("You already own a workspace");
    expect(dialog.textContent).not.toContain("workspace_create_limit_reached");
    expect(push).not.toHaveBeenCalled();
  });

  it("says a reserved slug is reserved", async () => {
    create.mockRejectedValue(new ApiError(400, [{ msg: "slug_reserved", code: "error" }]));
    await render();
    const dialog = await openDialog();
    await submit(dialog, "admin", "Admin");

    expect(dialog.textContent).toContain("reserved by the platform");
    expect(dialog.textContent).not.toContain("slug_reserved");
  });
});

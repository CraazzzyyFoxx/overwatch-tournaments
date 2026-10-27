// @vitest-environment happy-dom
//
// Signing in from the organizer page is a full-page OAuth round trip, so the
// form the visitor filled is a fresh mount when they land back. What they
// typed has to be there, and gone again once the community exists.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateForm } from "./CreateForm";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const openAuthModal = vi.fn();
const create = vi.fn();
const push = vi.fn();
let auth: { user: { id: number } | undefined };

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/hooks/useAuthProfile", () => ({ useAuthProfile: () => auth }));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ isDenied: () => false }) }));
vi.mock("@/stores/auth-modal.store", () => ({
  useAuthModalStore: (select: (state: { open: typeof openAuthModal }) => unknown) =>
    select({ open: openAuthModal })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (select: (state: { fetchWorkspaces: () => Promise<void> }) => unknown) =>
    select({ fetchWorkspaces: async () => {} })
}));
vi.mock("@/services/workspace.service", () => ({
  default: { create: (...args: unknown[]) => create(...args) }
}));

const SUBMIT = 'button[type="submit"]';

let container: HTMLDivElement;
let root: Root;

/** A page load: the form mounts from nothing, as it does after the redirect. */
function load() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root.render(<CreateForm year={2026} />));
}

function leave() {
  act(() => root.unmount());
  container.remove();
}

const field = (id: string) => container.querySelector<HTMLInputElement>(`#${id}`)!;

async function type(id: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(
      field(id),
      value
    );
    field(id).dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => container.querySelector<HTMLButtonElement>(SUBMIT)!.click());
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  auth = { user: undefined };
});

afterEach(() => {
  if (container?.isConnected) leave();
});

describe("the organizer page's create form", () => {
  it("comes back filled after the sign-in redirect, with the button next", async () => {
    load();
    await type("ws-name", "Funny Cup");
    await submit();
    expect(openAuthModal).toHaveBeenCalledOnce();

    leave();
    auth = { user: { id: 7 } };
    load();

    expect(field("ws-name").value).toBe("Funny Cup");
    expect(field("ws-slug").value).toBe("funny-cup");
    expect(document.activeElement).toBe(container.querySelector(SUBMIT));
  });

  it("starts empty once the community is created", async () => {
    load();
    await type("ws-name", "Funny Cup");
    await submit();
    leave();

    auth = { user: { id: 7 } };
    create.mockResolvedValue({ id: 42 });
    load();
    await submit();
    expect(create).toHaveBeenCalledWith({ name: "Funny Cup", slug: "funny-cup" });
    expect(push).toHaveBeenCalledWith("/admin/workspaces/new?id=42&step=profile");

    leave();
    load();
    expect(field("ws-name").value).toBe("");
    expect(field("ws-slug").value).toBe("");
  });
});

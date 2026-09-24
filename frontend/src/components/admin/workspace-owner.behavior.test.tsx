// @vitest-environment happy-dom
//
// Two different gates live on the same Owner block, and getting either wrong
// shows a co-administrator a button the backend will refuse:
//
//  - "Reassign owner" (stamp only) is superuser-only;
//  - "Transfer ownership" (stamp + the `owner` role) is for the workspace's own
//    owner as well as superusers — the person on the hook may get off it, a
//    `workspace.update` holder may not give away what they do not answer for.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";

import { WorkspaceOwnerControl, WorkspaceOwnerTransferControl } from "./workspace-owner";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getOwner = vi.fn();

vi.mock("@/services/workspace.service", () => ({
  default: {
    getOwner: (...args: unknown[]) => getOwner(...args),
    setOwner: vi.fn(),
    transferOwnership: vi.fn()
  }
}));

let currentUserId: number | undefined = 3;
vi.mock("@/stores/auth-profile.store", () => ({
  useAuthProfileStore: (selector: (state: { user?: { id?: number } }) => unknown) =>
    selector({ user: { id: currentUserId } })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

let container: HTMLDivElement;
let root: Root;

async function render(isSuperuser: boolean) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider
          client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
        >
          <WorkspaceOwnerControl workspaceId={8} isSuperuser={isSuperuser} />
          <WorkspaceOwnerTransferControl
            workspaceId={8}
            workspaceName="Rivals Cup"
            isSuperuser={isSuperuser}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // Let the owner query settle so the gates see a resolved owner.
  for (let turn = 0; turn < 4; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

beforeEach(() => {
  currentUserId = 3;
  getOwner.mockReset().mockResolvedValue({
    auth_user_id: 3,
    username: "ada",
    email: "ada@example.com",
    first_name: null,
    last_name: null,
    avatar_url: null
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("workspace owner controls", () => {
  it("offers the hand-off to the workspace's own owner, but not the stamp edit", async () => {
    await render(false);

    expect(container.querySelector("#workspace-owner-transfer")).not.toBeNull();
    expect(container.querySelector("#workspace-owner")).toBeNull();
  });

  it("offers neither to a workspace admin who is not the owner", async () => {
    currentUserId = 99;
    await render(false);

    expect(container.querySelector("#workspace-owner-transfer")).toBeNull();
    expect(container.querySelector("#workspace-owner")).toBeNull();
  });

  it("offers both to a superuser, owner or not", async () => {
    currentUserId = 99;
    await render(true);

    expect(container.querySelector("#workspace-owner-transfer")).not.toBeNull();
    expect(container.querySelector("#workspace-owner")).not.toBeNull();
  });
});

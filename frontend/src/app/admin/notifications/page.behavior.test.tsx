// @vitest-environment happy-dom
//
// The operator screen for the notifications a workspace produced. What is
// pinned here is what the server cannot tell the operator in time:
//
//  1. reading and retiring are separate grants, so a `notification.read` holder
//     must get the table with no retire control at all — offering one would be
//     a button that guarantees a 403;
//  2. a bulk retire is offered only with a kind chosen, and sends that kind
//     rather than the ids that happen to be on the page. The list is paged on
//     the server, so "retire every registration.approved" must not mean
//     "retire the 25 of them on this page";
//  3. a per-row retire goes through the confirmation and names exactly that id,
//     because the row it takes out of somebody's inbox is not recoverable from
//     this screen.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { NotificationAdminItem } from "@/types/notification.types";

import AdminWorkspaceNotificationsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listWorkspaceNotifications = vi.fn();
const retireWorkspaceNotifications = vi.fn();

let canRetire = true;
let workspaceId: number | null = 7;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) =>
      permission === "notification.delete" ? canRetire : true,
    isLoaded: true,
    isSuperuser: false
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number | null }) => unknown) =>
    selector({ currentWorkspaceId: workspaceId })
}));
vi.mock("@/services/notification.service", () => ({
  default: {
    listWorkspaceNotifications: (...args: unknown[]) => listWorkspaceNotifications(...args),
    retireWorkspaceNotifications: (...args: unknown[]) => retireWorkspaceNotifications(...args)
  }
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/notifications",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const LABEL = en.notifications.workspaceAdmin;

function row(overrides: Partial<NotificationAdminItem> = {}): NotificationAdminItem {
  return {
    id: 41,
    kind: "registration.approved",
    payload: { tournament_id: 5, tournament_name: "Autumn Cup", registration_id: 12 },
    recipient_auth_user_id: 500,
    recipient_username: "told",
    source_workspace_id: 7,
    published_at: "2026-09-01T10:00:00Z",
    expires_at: null,
    ...overrides
  };
}

function page(results: NotificationAdminItem[]) {
  return { results, total: results.length, page: 1, per_page: 25 };
}

const mounted: Root[] = [];

async function settle(turns = 6) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function mount(search = ""): Promise<HTMLElement> {
  window.history.replaceState(null, "", `/admin/notifications${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <AdminWorkspaceNotificationsPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(2);
}

function buttons(scope: ParentNode, label: string): HTMLButtonElement[] {
  return [...scope.querySelectorAll("button")].filter(
    (button) => (button.textContent ?? "").trim() === label
  );
}

/** The confirmation is portalled to `document.body`, not into the container. */
function confirmButton(): HTMLButtonElement | undefined {
  const dialog = document.body.querySelector("[role='alertdialog']");
  return dialog ? buttons(dialog, LABEL.retire.action)[0] : undefined;
}

afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
  vi.clearAllMocks();
});

beforeEach(() => {
  canRetire = true;
  workspaceId = 7;
  listWorkspaceNotifications.mockResolvedValue(page([row()]));
  retireWorkspaceNotifications.mockResolvedValue({ retired: 1 });
  document.body.innerHTML = "";
});

describe("/admin/notifications", () => {
  it("asks the server for this workspace's produced rows and renders them", async () => {
    const container = await mount();

    expect(listWorkspaceNotifications).toHaveBeenCalledWith(
      expect.objectContaining({ workspaceId: 7, kind: null, page: 1, perPage: 25 })
    );
    expect(container.textContent).toContain(LABEL.kinds.registration.approved);
    expect(container.textContent).toContain(LABEL.state.live);
  });

  it("gives a read-only operator no retire control at all", async () => {
    canRetire = false;

    const container = await mount("?kind=registration.approved");

    expect(buttons(container, LABEL.retire.action)).toHaveLength(0);
    expect(buttons(container, LABEL.retire.kindAction)).toHaveLength(0);
    expect(container.textContent).toContain(LABEL.readOnly);
  });

  it("retires one row by id, through the confirmation", async () => {
    const container = await mount();

    await click(buttons(container, LABEL.retire.action)[0]);
    expect(retireWorkspaceNotifications).not.toHaveBeenCalled();
    await click(confirmButton());

    expect(retireWorkspaceNotifications).toHaveBeenCalledWith({
      workspaceId: 7,
      ids: [41],
      kind: undefined
    });
  });

  it("offers the bulk retire only with a kind chosen, and sends the kind, not the loaded ids", async () => {
    const unfiltered = await mount();
    expect(buttons(unfiltered, LABEL.retire.kindAction)).toHaveLength(0);

    const filtered = await mount("?kind=registration.approved");
    expect(listWorkspaceNotifications).toHaveBeenLastCalledWith(
      expect.objectContaining({ kind: "registration.approved" })
    );

    await click(buttons(filtered, LABEL.retire.kindAction)[0]);
    await click(confirmButton());

    expect(retireWorkspaceNotifications).toHaveBeenCalledWith({
      workspaceId: 7,
      ids: undefined,
      kind: "registration.approved"
    });
  });

  it("shows an already-retired row without a retire button", async () => {
    listWorkspaceNotifications.mockResolvedValue(
      page([row({ expires_at: "2026-09-02T10:00:00Z" })])
    );

    const container = await mount();

    expect(container.textContent).toContain(LABEL.state.retired);
    expect(buttons(container, LABEL.retire.action)).toHaveLength(0);
  });

  it("says what to do when no workspace is selected instead of claiming a permission problem", async () => {
    workspaceId = null;

    const container = await mount();

    expect(container.textContent).toContain(LABEL.pickWorkspace);
    expect(listWorkspaceNotifications).not.toHaveBeenCalled();
  });
});

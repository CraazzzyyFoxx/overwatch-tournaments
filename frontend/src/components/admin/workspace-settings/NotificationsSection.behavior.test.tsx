// @vitest-environment happy-dom
//
// The workspace half of event notifications. What is pinned here:
//  1. no linked Discord server is not a form with dead controls — the channel
//     picker reads that guild's channels, so there is nothing to pick and the
//     only useful control is the link to the section that binds one;
//  2. a save sends exactly the three fields the RPC takes (channel, language,
//     kinds), with the channel as a STRING id or null — a snowflake does not
//     survive a JSON number;
//  3. the kind checkboxes are rendered from the server's catalogue, not from a
//     client-side copy of it;
//  4. a refused save says which of the three refusals it was: no guild, a
//     channel Discord would not confirm, or Discord being unreachable.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/error";
import type { NotificationWorkspaceConfig } from "@/types/notification.types";
import type { Workspace } from "@/types/workspace.types";
import { NotificationsSection } from "./NotificationsSection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getById = vi.fn();
const workspaceConfig = vi.fn();
const updateWorkspaceConfig = vi.fn();

vi.mock("@/services/workspace.service", () => ({
  default: {
    getById: (...args: unknown[]) => getById(...args),
    update: vi.fn()
  }
}));

vi.mock("@/services/notification.service", () => ({
  default: {
    workspaceConfig: (...args: unknown[]) => workspaceConfig(...args),
    updateWorkspaceConfig: (...args: unknown[]) => updateWorkspaceConfig(...args)
  }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/settings/notifications",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    isSuperuser: true,
    isWorkspaceAdmin: () => true,
    canAccessPermission: () => true
  })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), apiError: vi.fn() }
}));

const fetchWorkspaces = vi.fn();
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { fetchWorkspaces: () => void }) => unknown) =>
    selector({ fetchWorkspaces })
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

// The real picker is a popover over a Discord channel fetch; this section only
// needs a control that emits a channel id.
vi.mock("@/components/discord/DiscordChannelSelect", () => ({
  DiscordChannelSelect: ({ onChange }: { onChange: (id: string) => void }) => (
    <button type="button" onClick={() => onChange("555555555555555555")}>
      Pick channel
    </button>
  )
}));

const WORKSPACE = {
  id: 7,
  slug: "owt",
  name: "Overwatch Tournaments",
  is_active: true,
  is_hidden: false,
  discord_guild_id: null,
  discord_guild_verified_at: null
} as unknown as Workspace;

const LINKED = {
  ...WORKSPACE,
  discord_guild_id: "222222222222222222",
  discord_guild_verified_at: "2026-09-01T12:00:00Z"
} as Workspace;

const CONFIG: NotificationWorkspaceConfig = {
  workspace_id: 7,
  discord_guild_id: "222222222222222222",
  discord_channel_id: null,
  locale: "ru",
  broadcast_kinds: ["registration.opened", "check_in.opened"],
  broadcastable_kinds: ["registration.opened", "check_in.opened", "encounter.scheduled"]
};

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
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
      >
        <NotificationsSection workspaceId={7} />
      </QueryClientProvider>
    );
  });
  await settle();
}

async function click(node: Element | undefined | null) {
  expect(node).toBeTruthy();
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

function buttonIn(scope: ParentNode, label: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === label);
}

/** `SaveBar`'s own label, which the mocked translator renders as its message key. */
const SAVE = "save";

beforeEach(() => {
  fetchWorkspaces.mockReset();
  getById.mockReset().mockResolvedValue(LINKED);
  workspaceConfig.mockReset().mockResolvedValue(CONFIG);
  updateWorkspaceConfig.mockReset().mockImplementation((_id: number, body: unknown) =>
    Promise.resolve({ ...CONFIG, ...(body as object) })
  );
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Workspace settings › Notifications", () => {
  it("sends a workspace with no Discord server to the section that links one", async () => {
    getById.mockResolvedValue(WORKSPACE);
    await render();

    expect(container.textContent).toContain("No Discord server linked");
    expect(buttonIn(container, "Pick channel")).toBeUndefined();
    // Nothing is read before there is a guild whose channels could be offered.
    expect(workspaceConfig).not.toHaveBeenCalled();
    const link = [...container.querySelectorAll("a")].find((node) =>
      node.textContent?.includes("Open Discord settings")
    );
    expect(link?.getAttribute("href")).toBe("/admin/settings/discord");
  });

  it("offers the server's own catalogue of kinds, ticked as stored", async () => {
    await render();

    const boxes = [...container.querySelectorAll('[role="checkbox"]')];
    expect(boxes).toHaveLength(3);
    expect(boxes.map((box) => box.getAttribute("aria-checked"))).toEqual(["true", "true", "false"]);
  });

  it("saves the picked channel and kinds as one body, the channel id a string", async () => {
    await render();

    await click(buttonIn(container, "Pick channel"));
    const scheduled = container.querySelector("#broadcast-encounter\\.scheduled");
    await click(scheduled);
    await click(buttonIn(container, SAVE));

    expect(updateWorkspaceConfig).toHaveBeenCalledTimes(1);
    expect(updateWorkspaceConfig).toHaveBeenCalledWith(7, {
      discord_channel_id: "555555555555555555",
      locale: "ru",
      broadcast_kinds: ["registration.opened", "check_in.opened", "encounter.scheduled"]
    });
  });

  it("names the refusal instead of one flat failure", async () => {
    updateWorkspaceConfig.mockRejectedValue(
      new ApiError(503, [{ msg: "Could not reach Discord", code: "error" }])
    );
    await render();

    await click(buttonIn(container, "Pick channel"));
    await click(buttonIn(container, SAVE));

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("could not be reached");
    expect(alert?.textContent).not.toContain("no linked Discord server");
  });
});

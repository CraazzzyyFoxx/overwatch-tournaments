// @vitest-environment happy-dom
//
// The Discord guild picker. What is pinned here:
//  1. only servers this account can MANAGE are offered — the rest would be a
//     guaranteed 403 dressed up as a choice — and picking one posts that
//     guild id, never a typed snowflake (the field is gone from the PATCH);
//  2. 403, 409 and 503 are three different problems with three different
//     fixes, so they must not collapse into one "could not link" message;
//  3. no administered server is not an error: it almost always means the
//     Discord account is not linked, and the fix is one screen away;
//  4. a linked server can be unlinked, but only after a confirmation — it
//     takes Boosty roles and match-log channels offline;
//  5. the bound card shows who owns the Discord server, with their avatar.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { ManageableDiscordGuild, Workspace } from "@/types/workspace.types";
import { DiscordSection } from "./DiscordSection";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getById = vi.fn();
const myDiscordGuilds = vi.fn();
const verifyDiscordGuild = vi.fn();
const clearDiscordGuild = vi.fn();
const getDiscordGuildInfo = vi.fn();

vi.mock("@/services/workspace.service", () => ({
  default: {
    getById: (...args: unknown[]) => getById(...args),
    update: vi.fn(),
    myDiscordGuilds: (...args: unknown[]) => myDiscordGuilds(...args),
    verifyDiscordGuild: (...args: unknown[]) => verifyDiscordGuild(...args),
    clearDiscordGuild: (...args: unknown[]) => clearDiscordGuild(...args),
    getDiscordGuildInfo: (...args: unknown[]) => getDiscordGuildInfo(...args)
  }
}));

vi.mock("next/navigation", () => ({
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

const WORKSPACE: Workspace = {
  id: 7,
  slug: "owt",
  name: "Overwatch Tournaments",
  description: null,
  icon_url: null,
  is_active: true,
  is_hidden: false,
  timezone: "Europe/Moscow",
  branding_enabled: false,
  brand_primary: null,
  brand_secondary: null,
  brand_background: null,
  brand_surface: null,
  brand_accent: null,
  brand_foreground: null,
  brand_muted: null,
  brand_border: null,
  brand_ring: null,
  brand_destructive: null,
  subdomain: "owt",
  seo_title: null,
  seo_description: null,
  custom_domain: null,
  custom_domain_verified_at: null,
  custom_domain_verification_token: null,
  discord_guild_id: null,
  discord_guild_verified_at: null,
  verification_status: "unverified",
  default_division_grid_version_id: null,
  default_division_grid_version: null,
  newcomer_scope: "global"
};

const GUILDS: ManageableDiscordGuild[] = [
  {
    guild_id: "111111111111111111",
    name: "Owned Server",
    icon_url: "https://cdn.discordapp.com/icons/111/aaa.png",
    owner: true,
    can_manage: true
  },
  {
    guild_id: "222222222222222222",
    name: "Managed Server",
    icon_url: null,
    owner: false,
    can_manage: true
  },
  { guild_id: "333333333333333333", name: "Just A Member", owner: false, can_manage: false }
];

const BOUND: Workspace = {
  ...WORKSPACE,
  discord_guild_id: "222222222222222222",
  discord_guild_verified_at: "2026-09-01T12:00:00Z"
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
        <DiscordSection workspaceId={7} />
      </QueryClientProvider>
    );
  });
  await settle();
}

async function click(node: Element | undefined) {
  expect(node).toBeTruthy();
  await act(async () => {
    node?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

function buttonIn(scope: ParentNode, label: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === label);
}

beforeEach(() => {
  fetchWorkspaces.mockReset();
  getById.mockReset().mockResolvedValue(WORKSPACE);
  myDiscordGuilds.mockReset().mockResolvedValue(GUILDS);
  verifyDiscordGuild.mockReset().mockResolvedValue(BOUND);
  clearDiscordGuild.mockReset().mockResolvedValue(WORKSPACE);
  getDiscordGuildInfo.mockReset().mockResolvedValue({
    guild_id: null,
    connected: false,
    name: null,
    icon_url: null,
    member_count: 0,
    owner_id: null,
    owner_name: null,
    owner_avatar_url: null
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Workspace settings › Discord", () => {
  it("offers only the servers this account administers, and binds the one picked", async () => {
    await render();

    expect(container.textContent).toContain("Owned Server");
    expect(container.textContent).toContain("Managed Server");
    // Being in a server is not administering it; offering it would only ever
    // produce a 403.
    expect(container.textContent).not.toContain("Just A Member");

    const row = [...container.querySelectorAll("li")].find((node) =>
      node.textContent?.includes("Managed Server")
    );
    await click(buttonIn(row!, "Link this server"));

    expect(verifyDiscordGuild).toHaveBeenCalledWith(7, "222222222222222222");
  });

  it("says a claimed server is claimed, not that the account lost access", async () => {
    verifyDiscordGuild.mockRejectedValue(
      new ApiError(409, [{ msg: "This Discord guild is already linked", code: "error" }])
    );
    await render();

    await click(buttonIn(container, "Link this server"));

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("Another workspace has already claimed that server");
    expect(alert?.textContent).not.toContain("no longer administer");
  });

  it("says the account lost access when Discord refuses, not that it is taken", async () => {
    verifyDiscordGuild.mockRejectedValue(
      new ApiError(403, [{ msg: "You do not administer this Discord guild", code: "error" }])
    );
    await render();

    await click(buttonIn(container, "Link this server"));

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("no longer administer");
    expect(alert?.textContent).not.toContain("already claimed");
  });

  it("separates a Discord outage from a refusal", async () => {
    verifyDiscordGuild.mockRejectedValue(
      new ApiError(503, [{ msg: "Could not reach Discord for guild verification", code: "error" }])
    );
    await render();

    await click(buttonIn(container, "Link this server"));

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("could not be reached");
    expect(alert?.textContent).not.toContain("already claimed");
    expect(alert?.textContent).not.toContain("no longer administer");
  });

  it("sends an account with no administered server to account settings", async () => {
    myDiscordGuilds.mockResolvedValue([GUILDS[2]]);
    await render();

    expect(container.textContent).toContain("You do not administer any Discord server");
    expect(buttonIn(container, "Link this server")).toBeUndefined();
    const link = [...container.querySelectorAll("a")].find((node) =>
      node.textContent?.includes("Open account settings")
    );
    expect(link?.getAttribute("href")).toBe("/?settings=profile");
  });

  it("will not unlink a live server without a confirmation", async () => {
    getById.mockResolvedValue(BOUND);
    getDiscordGuildInfo.mockResolvedValue({
      guild_id: "222222222222222222",
      connected: true,
      name: "Managed Server",
      icon_url: "https://cdn.discordapp.com/icons/222/bbb.png",
      member_count: 48,
      owner_id: "99",
      owner_name: "Ada",
      owner_avatar_url: "https://cdn.discordapp.com/avatars/99/ada.png"
    });
    await render();

    expect(container.textContent).toContain("Owner · Ada");
    expect(buttonIn(container, "Unlink server")).toBeTruthy();

    await click(buttonIn(container, "Unlink server"));

    const dialog = document.querySelector('[role="alertdialog"]');
    expect(dialog?.textContent).toContain("Unlink Discord server");
    expect(dialog?.textContent).toContain("Overwatch Tournaments");
    expect(clearDiscordGuild).not.toHaveBeenCalled();

    await click(buttonIn(dialog!, "Unlink server"));
    expect(clearDiscordGuild).toHaveBeenCalledWith(7);
  });
});

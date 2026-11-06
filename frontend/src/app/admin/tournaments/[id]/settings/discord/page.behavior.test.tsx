// @vitest-environment happy-dom
//
// Carried over from `TournamentSettingsTab.behavior.test`. The Discord channel
// is its own resource, not a field of the tournament: saving it must not write
// the tournament, and a channel that was never chosen must not be saved at all.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Tournament } from "@/types/tournament.types";
import DiscordSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getTournament = vi.fn();
const getDiscordChannel = vi.fn();
const setDiscordChannel = vi.fn();
const updateTournament = vi.fn();
const getVoice = vi.fn();
const putVoice = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: (...args: unknown[]) => getTournament(...args),
    getDiscordChannel: (...args: unknown[]) => getDiscordChannel(...args),
    setDiscordChannel: (...args: unknown[]) => setDiscordChannel(...args),
    updateTournament: (...args: unknown[]) => updateTournament(...args),
    getVoice: (...args: unknown[]) => getVoice(...args),
    putVoice: (...args: unknown[]) => putVoice(...args),
    syncVoice: vi.fn(),
    deleteDiscordChannel: vi.fn(),
    backfillDiscordChannel: vi.fn()
  }
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "64" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessPermission: () => true })
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), info: vi.fn(), apiError: vi.fn() }
}));

vi.mock("next-intl", async (importOriginal) => {
  const actual = await importOriginal<typeof import("next-intl")>();
  const { default: en } = await import("@/i18n/messages/en.json");
  return {
    ...actual,
    useTranslations: (namespace?: string) =>
      actual.createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
    useLocale: () => "en",
    useTimeZone: () => "UTC"
  };
});

// No Discord guild is reachable in a test, and a pending channel list renders
// a disabled combobox rather than the manual-ID fallback — so the fallback is
// what this test drives, deterministically.
vi.mock("@/hooks/useDiscordEntities", () => ({
  useDiscordChannels: () => ({ data: [], isLoading: false, refetch: vi.fn() }),
  useDiscordRoles: () => ({
    data: { roles: [{ id: "5", name: "Staff", managed: false }] },
    isLoading: false,
    refetch: vi.fn()
  })
}));

const TOURNAMENT = {
  id: 64,
  workspace_id: 1,
  name: "OWT 64",
  slug: "owt-64",
  status: "live",
  stages: []
} as unknown as Tournament;

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
        <DiscordSettingsPage />
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Opens the channel dialog and returns the form portalled out of the page. */
async function openChannelDialog() {
  const addChannel = [...container.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Add channel")
  );
  await act(async () => {
    addChannel?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();

  const dialogForm = [...document.querySelectorAll("form")].find(
    (form) => !container.contains(form)
  );
  if (!dialogForm) throw new Error("channel dialog not rendered");
  return dialogForm;
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      globalThis.HTMLInputElement.prototype,
      "value"
    )?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle(2);
}

const VOICE_SETTINGS = {
  enabled: false,
  private: true,
  early_teams: false,
  category_id: null,
  staff_role_ids: ["5"]
};

const VOICE_STATUS = {
  settings: VOICE_SETTINGS,
  guild_linked: true,
  channels: [
    {
      slot_key: "hub",
      kind: "hub",
      name: "Общий · OWT 64",
      discord_channel_id: "111",
      status: "active"
    },
    {
      slot_key: "team:3",
      kind: "team",
      name: "Rockets",
      discord_channel_id: "222",
      status: "active"
    }
  ],
  warnings: [
    { code: "player_without_discord", workspace_member_id: 1, name: "Ann", team_id: 3 },
    { code: "player_without_discord", workspace_member_id: 2, name: "Bob", team_id: 3 }
  ],
  sync_issues: [
    { code: "missing_permission:manage_roles", detail: null },
    { code: "something_new", detail: null }
  ],
  last_synced_at: null
};

function buttonByText(text: string) {
  return [...document.querySelectorAll("button")].find(
    (button) => button.textContent?.trim() === text
  );
}

async function click(element: Element | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle();
}

beforeEach(() => {
  getVoice.mockReset().mockResolvedValue(VOICE_STATUS);
  putVoice.mockReset().mockResolvedValue(VOICE_STATUS);
  getTournament.mockReset().mockResolvedValue(TOURNAMENT);
  getDiscordChannel.mockReset().mockResolvedValue(null);
  setDiscordChannel.mockReset().mockResolvedValue(undefined);
  updateTournament.mockReset().mockResolvedValue(TOURNAMENT);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

describe("Settings › Discord", () => {
  it("says the channel is not configured, and offers to add one", async () => {
    await render();

    expect(container.textContent).toContain("No channel yet");
  });

  it("saves the channel without saving the tournament with it", async () => {
    await render();
    const dialogForm = await openChannelDialog();

    // No guild is reachable in tests, so the picker offers its manual fallback.
    await type(
      dialogForm.querySelector<HTMLInputElement>("#discord-channel-id")!,
      "987654321098765432"
    );

    await act(async () => {
      dialogForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await settle();

    expect(setDiscordChannel).toHaveBeenCalledTimes(1);
    expect(updateTournament).not.toHaveBeenCalled();
  });

  it("refuses to save a channel that was never chosen", async () => {
    await render();
    const dialogForm = await openChannelDialog();

    await act(async () => {
      dialogForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await settle();

    expect(setDiscordChannel).not.toHaveBeenCalled();
    expect(dialogForm.querySelector("[role=alert]")?.textContent).toContain("Pick the channel");
  });

  it.each([
    ["#settings-discord-broadcasts", "discord_broadcasts_enabled"],
    ["#settings-discord-dms", "discord_dms_enabled"]
  ])("switching %s off saves only %s", async (selector, field) => {
    await render();
    const toggle = () => container.querySelector(selector)!;
    expect(toggle().getAttribute("aria-checked")).toBe("true");

    await act(async () => {
      toggle().dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();
    await act(async () => {
      [...document.querySelectorAll("button")]
        .find((button) => button.textContent?.trim() === "Save changes")
        ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(updateTournament).toHaveBeenCalledWith(64, { [field]: false });
    expect(setDiscordChannel).not.toHaveBeenCalled();
  });

  describe("voice channels", () => {
    it("shows sync issues and players without Discord, grouped by team", async () => {
      await render();

      expect(container.textContent).toContain("The bot lacks the permission: manage_roles.");
      expect(container.textContent).toContain("something_new");
      expect(container.textContent).toContain("Rockets: Ann, Bob");
    });

    it("saves a draft with an automatic category as null", async () => {
      await render();
      await click(container.querySelector("#voice-enabled")!);
      await click(buttonByText("Save"));

      expect(putVoice).toHaveBeenCalledWith(64, { ...VOICE_SETTINGS, enabled: true });
    });

    it("asks before deleting every channel, then turns the feature off", async () => {
      getVoice.mockResolvedValue({
        ...VOICE_STATUS,
        settings: { ...VOICE_SETTINGS, enabled: true, category_id: "42" }
      });
      await render();
      await click(buttonByText("Delete all channels"));

      expect(putVoice).not.toHaveBeenCalled();
      await click(buttonByText("Delete channels"));

      expect(putVoice).toHaveBeenCalledWith(64, {
        ...VOICE_SETTINGS,
        enabled: false,
        category_id: "42"
      });
    });
  });
});

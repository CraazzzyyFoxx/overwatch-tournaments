// @vitest-environment happy-dom
//
// The only place a reader can stop the bot writing to them. Two things make it
// work rather than merely render:
//
//  1. one switch writes ONE group. A full-row PUT here would silently re-enable
//     a group the reader turned off in another tab, and the server's answer is
//     what the switches must then show — not the optimistic guess;
//  2. with no Discord account linked the switches are honest but pointless, so
//     the panel says so and points at the tab that fixes it. Silence there
//     reads as "DMs are on", which is exactly wrong.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NotificationsSection from "@/components/account-settings/NotificationsSection";
import type { NotificationPreferences } from "@/types/notification.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const preferences = vi.fn();
const updatePreferences = vi.fn();
const setActiveTab = vi.fn();

vi.mock("@/services/notification.service", () => ({
  default: {
    preferences: () => preferences(),
    updatePreferences: (body: unknown) => updatePreferences(body)
  }
}));

// Labels come through as their message keys; this panel's contract is the
// payload it writes, not the copy.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));
vi.mock("@/stores/account-settings-modal.store", () => ({
  useAccountSettingsModalStore: (
    select: (state: { setActiveTab: (tab: string) => void }) => unknown
  ) => select({ setActiveTab })
}));

const LINKED: NotificationPreferences = {
  discord_dm: { tournament: true, matches: true, team: true },
  discord_linked: true
};

function tick(ms = 0) {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <NotificationsSection />
      </QueryClientProvider>
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function switchFor(scope: ParentNode, group: string): HTMLButtonElement {
  const found = scope.querySelector<HTMLButtonElement>(
    `[role="switch"][aria-labelledby="dm-${group}-label"]`
  );
  if (!found) throw new Error(`Expected the ${group} switch`);
  return found;
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await act(async () => {
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  setActiveTab.mockReset();
  preferences.mockReset().mockResolvedValue(LINKED);
  updatePreferences.mockReset().mockImplementation((body: { discord_dm: Record<string, boolean> }) =>
    Promise.resolve({
      discord_dm: { ...LINKED.discord_dm, ...body.discord_dm },
      discord_linked: true
    })
  );
});

describe("NotificationsSection", () => {
  it("writes only the group that moved, and shows what the server answered", async () => {
    const container = await mount();
    expect(switchFor(container, "matches").getAttribute("aria-checked")).toBe("true");

    await click(switchFor(container, "matches"));

    expect(updatePreferences).toHaveBeenCalledTimes(1);
    expect(updatePreferences).toHaveBeenCalledWith({ discord_dm: { matches: false } });
    expect(switchFor(container, "matches").getAttribute("aria-checked")).toBe("false");
    // The groups nobody touched are untouched, on the wire and on screen.
    expect(switchFor(container, "tournament").getAttribute("aria-checked")).toBe("true");
    expect(switchFor(container, "team").getAttribute("aria-checked")).toBe("true");
  });

  it("keeps the stored value when the write fails instead of showing the guess", async () => {
    updatePreferences.mockRejectedValue(new Error("offline"));
    const container = await mount();

    await click(switchFor(container, "team"));

    expect(switchFor(container, "team").getAttribute("aria-checked")).toBe("true");
  });

  it("says DMs have nowhere to go until Discord is linked, and offers the tab that links it", async () => {
    preferences.mockResolvedValue({ ...LINKED, discord_linked: false });
    const container = await mount();

    expect(container.textContent).toContain("notifications.linkDiscordHint");
    const link = [...container.querySelectorAll("button")].find(
      (node) => node.textContent?.trim() === "notifications.linkDiscordAction"
    );
    await click(link!);
    expect(setActiveTab).toHaveBeenCalledWith("profile");
  });

  it("does not nag an account that already linked Discord", async () => {
    const container = await mount();

    expect(container.textContent).not.toContain("notifications.linkDiscordHint");
  });
});

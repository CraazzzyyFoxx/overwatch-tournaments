// @vitest-environment happy-dom
//
// The host's bot lobby on the live stage: create with the remembered region, count the minutes down while the bot is
// there, offer Recreate once it has left.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { MixBotLobby } from "@/services/custom-game.service";

import type { BotLobbyOptions } from "../pickup-bot-lobby";
import { BotLobbyControl } from "./BotLobbyControl";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const NOW = Date.parse("2026-11-01T20:00:00Z");
let clock: number | null = NOW;
vi.mock("@/hooks/useMinuteClock", () => ({ useMinuteClock: () => clock }));

let root: Root | null = null;

function mount(botLobby: MixBotLobby | null, onCreate = vi.fn(), overrides: Partial<BotLobbyOptions> = {}) {
  const host = document.body.appendChild(document.createElement("div"));
  root = createRoot(host);
  act(() =>
    root!.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <BotLobbyControl
          options={{
            regions: ["europe", "eu_poland"],
            defaultRegion: "europe",
            rememberedRegion: "eu_poland",
            creating: false,
            onCreate,
            ...overrides
          }}
          botLobby={botLobby}
        />
      </NextIntlClientProvider>
    )
  );
  return { host, onCreate };
}

const lobbyExpiringIn = (minutes: number): MixBotLobby => ({
  party_code: "ABC123",
  created_at: new Date(NOW - (15 - minutes) * 60_000).toISOString(),
  expires_at: new Date(NOW + minutes * 60_000).toISOString(),
  match_id: null
});

const button = (host: HTMLElement, label: string) =>
  [...host.querySelectorAll("button")].find((node) => node.textContent?.includes(label));

afterEach(() => {
  act(() => root?.unmount());
  document.body.innerHTML = "";
  clock = NOW;
});

describe("BotLobbyControl", () => {
  it("creates the lobby in the host's remembered region and warns to start within 15 minutes", () => {
    const { host, onCreate } = mount(null);

    expect(host.textContent).toContain("within 15 minutes");
    act(() => button(host, "Create lobby via bot")?.click());

    expect(onCreate).toHaveBeenCalledWith("eu_poland");
  });

  it("counts the minutes left while the bot is in the lobby, with nothing to create", () => {
    const { host } = mount(lobbyExpiringIn(12));

    expect(host.textContent).toContain("12 minutes left");
    expect(button(host, "Create lobby via bot")).toBeUndefined();
    expect(button(host, "Recreate")).toBeUndefined();
  });

  it("offers Recreate once the 15 minutes have passed", () => {
    clock = NOW + 16 * 60_000;
    const { host, onCreate } = mount(lobbyExpiringIn(15));

    expect(host.textContent).toContain("The bot has left the lobby");
    expect(host.textContent).not.toContain("within 15 minutes");
    act(() => button(host, "Recreate")?.click());

    expect(onCreate).toHaveBeenCalledWith("eu_poland");
  });
});

// @vitest-environment happy-dom
//
// The tabs are the only way a host reaches lobby B, so three things are
// load-bearing:
//
//  1. a one-lobby mix renders nothing at all -- the control would be a tab bar
//     with a single tab, which is chrome describing itself;
//  2. picking a tab reports the lobby to the page, which owns `activeLobby`;
//  3. each tab carries the state a host decides on without opening it: which
//     game that lobby is on, whether its current lineup is still unrecorded,
//     and what it is about to play.
//
// Every string here is a `mixes.lobbies.*` message, so next-intl is mocked to
// echo the key (and its arguments) rather than a translation -- the same shape
// the other mix-board behaviour tests use.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGameLobby } from "@/services/custom-game.service";
import type { MapRead } from "@/types/map.types";

import { PickupLobbyTabs } from "./PickupLobbyTabs";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// `key` alone, or `key:arg,arg` when the message interpolates: the lobby
// status is the one place a VALUE is load-bearing (which game the lobby is on),
// so the mock keeps the arguments instead of collapsing to the key.
vi.mock("next-intl", () => ({
  useTranslations:
    () =>
    (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${Object.values(values).join(",")}` : key,
}));

const onSelect = vi.fn();

const CONTROL = { id: 1, name: "Control", slug: "control", image_path: "", description: "", aliases: [] };

function mapRead(id: number, name: string): MapRead {
  return {
    id,
    created_at: new Date(0),
    updated_at: null,
    name,
    image_path: "",
    gamemode_id: CONTROL.id,
    in_competitive: true,
    aliases: [],
    gamemode: CONTROL,
  };
}

const CATALOGUE = [mapRead(6, "Ilios"), mapRead(7, "Busan")];

function lobbyRow(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    balance_result: null,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(lobbies: CustomGameLobby[], activeLobby: 0 | 1 = 0) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupLobbyTabs
        lobbies={lobbies}
        activeLobby={activeLobby}
        maps={CATALOGUE}
        onSelect={onSelect}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function tabs(scope: ParentNode) {
  return [...scope.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  onSelect.mockReset();
});

describe("PickupLobbyTabs", () => {
  it("renders nothing for a mix that runs one lobby", async () => {
    const scope = await mount([lobbyRow()]);

    expect(tabs(scope)).toHaveLength(0);
    expect(scope.textContent).toBe("");
  });

  it("switches the page to the lobby the host picked", async () => {
    const scope = await mount([lobbyRow(), lobbyRow({ lobby_index: 1 })]);

    expect(tabs(scope).map((node) => node.getAttribute("aria-selected"))).toEqual(["true", "false"]);

    await click(tabs(scope)[1]);

    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("marks the tab the page is already on instead of reporting it again", async () => {
    const scope = await mount([lobbyRow(), lobbyRow({ lobby_index: 1 })], 1);

    expect(tabs(scope).map((node) => node.getAttribute("aria-selected"))).toEqual(["false", "true"]);

    await click(tabs(scope)[1]);

    expect(onSelect).not.toHaveBeenCalled();
  });

  it("says which game each lobby is on, and names the map it is about to play", async () => {
    const scope = await mount([
      lobbyRow({ matches_count: 4, next_map_id: 6 }),
      lobbyRow({ lobby_index: 1, matches_count: 2, next_map_id: 7 }),
    ]);

    expect(tabs(scope)[0].textContent).toContain("tab:A");
    expect(tabs(scope)[0].textContent).toContain("game:5");
    expect(tabs(scope)[0].textContent).toContain("Ilios");
    expect(tabs(scope)[1].textContent).toContain("tab:B");
    expect(tabs(scope)[1].textContent).toContain("game:3");
    expect(tabs(scope)[1].textContent).toContain("Busan");
  });

  it("flags a lobby whose balanced lineup has not been recorded yet", async () => {
    const scope = await mount([
      lobbyRow(),
      lobbyRow({ lobby_index: 1, lineup_recorded: false }),
    ]);

    expect(tabs(scope)[0].textContent).not.toContain("notRecorded");
    expect(tabs(scope)[1].textContent).toContain("notRecorded");
  });

  it("says nothing about a lobby that has never been balanced", async () => {
    const scope = await mount([
      lobbyRow(),
      lobbyRow({ lobby_index: 1, balanced_at: null, lineup_recorded: true, matches_count: 0 }),
    ]);

    expect(tabs(scope)[1].textContent).toContain("notBalanced");
    expect(tabs(scope)[1].textContent).not.toContain("game:1");
  });
});

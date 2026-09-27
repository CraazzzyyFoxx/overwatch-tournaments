// @vitest-environment happy-dom
//
// Mix identity moved out of the teams column into this header, so the
// contracts that used to be pinned there are pinned here:
//
//  1. the open mix is named with its id, so two mixes called "Thursday scrim"
//     are still tellable apart;
//  2. a viewer who cannot host gets no Add players;
//  3. Add players is inert until a mix has actually loaded.
//
// Switching mixes and creating one moved to the list at `/balancer/mix` --
// those contracts live in `PickupMixList.behavior.test.tsx` now.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGame } from "@/services/custom-game.service";

import { PickupMixHeader } from "./PickupMixHeader";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const onOpenPool = vi.fn();
const onOpenAccess = vi.fn();
const onSetSelfService = vi.fn();
const onPostSignup = vi.fn();

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 12,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: "Host",
    name: "Thursday scrim",
    status: "balanced",
    created_at: "2026-01-01T00:00:00Z",
    lobby_count: 1,
    lobbies: [
      {
        lobby_index: 0,
        balance_result: null,
        selected_variant_index: 0,
        next_map_id: null,
        balanced_at: null,
        lineup_recorded: true,
        matches_count: 0,
      },
    ],
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: "555" },
    ...overrides,
  } as CustomGame;
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const roots: { unmount: () => void }[] = [];

async function mount(
  currentGame: CustomGame | undefined,
  props: { canWrite?: boolean; gameLoading?: boolean } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupMixHeader
        canWrite={props.canWrite ?? true}
        game={currentGame}
        gameLoading={props.gameLoading ?? false}
        onOpenPool={onOpenPool}
        onOpenAccess={onOpenAccess}
        onSetSelfService={onSetSelfService}
        onPostSignup={onPostSignup}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

beforeEach(() => {
  while (roots.length > 0) {
    const root = roots.pop();
    act(() => root?.unmount());
  }
  document.body.innerHTML = "";
  onOpenPool.mockReset();
  onOpenAccess.mockReset();
  onSetSelfService.mockReset();
  onPostSignup.mockReset();
});

describe("PickupMixHeader", () => {
  it("names the open mix with its id", async () => {
    const scope = await mount(game());

    expect(scope.textContent).toContain("Thursday scrim");
    expect(scope.textContent).toContain("#12");
  });

  it("says no mix yet once loading settles on nothing", async () => {
    const loading = await mount(undefined, { gameLoading: true });
    expect(loading.textContent).toContain("\u2026");

    const settled = await mount(undefined, { gameLoading: false });
    expect(settled.textContent).toContain("No mix yet");
  });

  it("gives a viewer who cannot write no way to write", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(byName(scope, "Add players")).toBeNull();
    // Reading which mix is open is not a write.
    expect(scope.textContent).toContain("Thursday scrim");
  });

  it("disables Add players until a mix has loaded", async () => {
    const scope = await mount(undefined);

    expect(byName(scope, "Add players")?.hasAttribute("disabled")).toBe(true);
  });

  it("opens the workspace pool on request", async () => {
    const scope = await mount(game());

    await click(byName(scope, "Add players"));

    expect(onOpenPool).toHaveBeenCalledTimes(1);
  });

  it("opens the access dialog on request", async () => {
    const scope = await mount(game());

    await click(scope.querySelector('[aria-label="Manage access"]'));

    expect(onOpenAccess).toHaveBeenCalledTimes(1);
  });

  it("hides the access control from a viewer who cannot write", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(scope.querySelector('[aria-label="Manage access"]')).toBeNull();
  });
});

// The host's self-service switches. `next-intl` is mocked to echo the key, so
// every label below is the message key rather than the rendered sentence.
describe("PickupMixHeader self-service", () => {
  it("writes the signup mode the host picked", async () => {
    const scope = await mount(game({ self_signup: "closed" }));

    await click(byName(scope, "signup.pool"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "pool" });
  });

  it("marks the mode the mix is actually in", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    const checked = [...scope.querySelectorAll('[role="radio"]')]
      .filter((node) => node.getAttribute("aria-checked") === "true")
      .map((node) => node.textContent?.trim());

    expect(checked).toEqual(["signup.benched"]);
  });

  it("writes the role-edit switch on its own", async () => {
    const scope = await mount(game({ self_role_edit: false }));

    await click(scope.querySelector('[aria-label="roleEdit"]'));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_role_edit: true });
  });

  it("posts the signup card in the mode the mix is in", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    await click(byName(scope, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("benched");
  });

  it("falls a closed mix back to the pool when posting", async () => {
    const scope = await mount(game({ self_signup: "closed" }));

    await click(byName(scope, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("pool");
  });

  it("cannot post a signup card with no mix channel", async () => {
    const scope = await mount(
      game({ settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null } }),
    );

    const button = byName(scope, "openInDiscord");
    expect(button?.hasAttribute("disabled")).toBe(true);
    expect(button?.getAttribute("title")).toBe("noChannel");
  });

  it("shows a viewer who cannot write none of it", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(byName(scope, "signup.pool")).toBeNull();
    expect(byName(scope, "openInDiscord")).toBeNull();
    expect(scope.querySelector('[aria-label="roleEdit"]')).toBeNull();
  });
});

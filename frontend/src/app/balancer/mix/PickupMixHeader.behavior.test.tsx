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

import type { CustomGame, CustomGameDiscordPost } from "@/services/custom-game.service";

import { PickupMixHeader } from "./PickupMixHeader";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Echoes the key, plus any interpolated values -- so a label built from a
// slot (`posts.lineupLobby`) is checkable without the real messages.
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}(${Object.values(values).join(",")})` : key
}));

const onOpenPool = vi.fn();
const onOpenAccess = vi.fn();
const onSetSelfService = vi.fn();
const onPostSignup = vi.fn();
const onLobbyCountChange = vi.fn();
const onShuffleAll = vi.fn();
const onDeleteDiscordPost = vi.fn();

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
        matches_count: 0
      }
    ],
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: "555" },
    ...overrides
  } as CustomGame;
}

function lobbyRow(lobbyIndex: 0 | 1, overrides: Record<string, unknown> = {}) {
  return {
    lobby_index: lobbyIndex,
    balance_result: null,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    ...overrides
  } as CustomGame["lobbies"][number];
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const roots: { unmount: () => void }[] = [];

async function mount(
  currentGame: CustomGame | undefined,
  props: { canWrite?: boolean; gameLoading?: boolean } = {}
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
        settingLobbyCount={false}
        onLobbyCountChange={onLobbyCountChange}
        shufflingAll={false}
        onShuffleAll={onShuffleAll}
        onDeleteDiscordPost={onDeleteDiscordPost}
      />
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
  return (
    [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null
  );
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
  onLobbyCountChange.mockReset();
  onShuffleAll.mockReset();
  onDeleteDiscordPost.mockReset();
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

  // The lobby controls. `next-intl` is mocked to echo the key, so every label
  // below is the message key rather than the rendered sentence.
  it("opens a second lobby on request", async () => {
    const scope = await mount(game());

    await click(byName(scope, "2"));

    expect(onLobbyCountChange).toHaveBeenCalledWith(2);
  });

  it("does not re-send the lobby count the mix already runs", async () => {
    const scope = await mount(game());

    await click(byName(scope, "1"));

    expect(onLobbyCountChange).not.toHaveBeenCalled();
  });

  it("asks before dropping a lobby, because its balance goes with it", async () => {
    const scope = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }));

    await click(byName(scope, "1"));
    expect(onLobbyCountChange).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "dropDescription"
    );

    await click(byName(document, "dropConfirm"));
    expect(onLobbyCountChange).toHaveBeenCalledWith(1);
  });

  it("offers the shared reshuffle only once the mix runs two lobbies", async () => {
    const one = await mount(game());
    expect(byName(one, "shuffleAll")).toBeNull();

    const two = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }));
    await click(byName(two, "shuffleAll"));

    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("asks before a shared reshuffle while some lobby's lineup is unrecorded", async () => {
    const scope = await mount(
      game({
        lobby_count: 2,
        lobbies: [lobbyRow(0), lobbyRow(1, { lineup_recorded: false })]
      })
    );

    await click(byName(scope, "shuffleAll"));
    expect(onShuffleAll).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "shuffleDescription"
    );

    await click(byName(document, "shuffleConfirm"));
    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("gives a viewer no lobby controls at all", async () => {
    const scope = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }), {
      canWrite: false
    });

    expect(byName(scope, "shuffleAll")).toBeNull();
    expect(byName(scope, "2")).toBeNull();
  });
});

// The host's self-service switches, behind the Signup trigger. `next-intl` is
// mocked to echo the key, so every label below is the message key rather than
// the rendered sentence. The popover portals to `document.body`.
function signupTrigger(scope: ParentNode) {
  return scope.querySelector('[aria-label^="signupTrigger"]');
}

async function openSignup(scope: ParentNode) {
  await click(signupTrigger(scope));
  return document;
}

describe("PickupMixHeader self-service", () => {
  it("writes the signup mode the host picked", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "closed" })));

    await click(byName(popover, "signup.pool"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "pool" });
  });

  it("shows the mode the mix is actually in, on the trigger and in the popover", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    expect(signupTrigger(scope)?.getAttribute("aria-label")).toBe("signupTrigger(signup.benched)");

    const popover = await openSignup(scope);
    const checked = [...popover.querySelectorAll('[role="radio"]')]
      .filter((node) => node.getAttribute("aria-checked") === "true")
      .map((node) => node.textContent?.trim());

    expect(checked).toEqual(["signup.benched"]);
    expect(popover.body.textContent).toContain("signupHint.benched");
  });

  it("writes the role-edit switch on its own", async () => {
    const popover = await openSignup(await mount(game({ self_role_edit: false })));

    await click(popover.querySelector('[aria-label="roleEdit"]'));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_role_edit: true });
  });

  it("posts the signup card in the mode the mix is in", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "benched" })));

    await click(byName(popover, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("benched");
  });

  it("falls a closed mix back to the pool when posting", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "closed" })));

    await click(byName(popover, "openInDiscord"));

    expect(onPostSignup).toHaveBeenCalledWith("pool");
  });

  it("cannot post a signup card with no mix channel", async () => {
    const popover = await openSignup(
      await mount(
        game({
          settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null }
        })
      )
    );

    const button = byName(popover, "openInDiscord");
    expect(button?.hasAttribute("disabled")).toBe(true);
    expect(button?.getAttribute("title")).toBe("noChannel");
  });

  it("shows a viewer who cannot write none of it", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(signupTrigger(scope)).toBeNull();
  });
});

// The signup post's state, on the trigger and inside the popover. The bot
// answers asynchronously, so this is the only way a host learns a post
// landed -- or why it did not -- and the only way to take one down.
function post(overrides: Partial<CustomGameDiscordPost> = {}): CustomGameDiscordPost {
  return {
    id: 1,
    slot: "signup",
    kind: "mix.signup",
    status: "posted",
    url: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides
  };
}

describe("PickupMixHeader signup post status", () => {
  async function status(scope: ParentNode) {
    return (await openSignup(scope)).querySelector('[role="status"]');
  }

  it("says nothing about a post that was never made", async () => {
    const scope = await mount(game({ discord_posts: [] }));

    expect(signupTrigger(scope)?.getAttribute("aria-label")).toBe("signupTrigger(signup.closed)");
    const region = await status(scope);
    expect(region?.textContent).toBe("");
    expect(region?.querySelector("a")).toBeNull();
  });

  it("reads the newest signup post, not an older one or a lineup card", async () => {
    const url = "https://discord.com/channels/1/2/3";
    const scope = await mount(
      game({
        discord_posts: [
          post({ id: 1, status: "failed", error: "Missing Permissions" }),
          post({ id: 2, status: "posted", url }),
          post({ id: 3, slot: "lineup:0:1", kind: "mix.lineup", status: "pending" })
        ]
      })
    );

    expect(signupTrigger(scope)?.getAttribute("aria-label")).toBe(
      "signupTriggerPost(signup.closed,post.posted)"
    );
    const link = (await status(scope))?.querySelector("a");
    expect(link?.getAttribute("href")).toBe(url);
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.textContent).toBe("post.posted");
  });

  it("exposes Discord's refusal on a failed post", async () => {
    const scope = await mount(
      game({ discord_posts: [post({ status: "failed", error: "Missing Permissions" })] })
    );

    expect(signupTrigger(scope)?.getAttribute("aria-label")).toBe(
      "signupTriggerPost(signup.closed,post.failed)"
    );
    expect((await status(scope))?.textContent).toContain("Missing Permissions. post.failedHint");
  });

  it("tells the host a lost post never reached Discord", async () => {
    const region = await status(await mount(game({ discord_posts: [post({ status: "lost" })] })));

    expect(region?.textContent).toContain("post.lost");
    expect(region?.textContent).toContain("post.lostHint");
  });
});

describe("PickupMixHeader Discord posts menu", () => {
  const twoLobbies = { lobby_count: 2 as const, lobbies: [lobbyRow(0), lobbyRow(1)] };

  it("is not offered while the mix has no posts", async () => {
    const scope = await mount(game({ discord_posts: [] }));

    expect(byName(scope, "posts.menu0")).toBeNull();
  });

  it("lists every post, lineup cards by lobby and game", async () => {
    const url = "https://discord.com/channels/1/2/3";
    const scope = await mount(
      game({
        ...twoLobbies,
        discord_posts: [
          post({ id: 1, url }),
          post({ id: 2, slot: "lineup:1:3", kind: "mix.lineup", status: "pending" })
        ]
      })
    );

    await click(byName(scope, "posts.menu2"));

    const rows = [...document.querySelectorAll('[aria-label="posts.menu"] li')];
    expect(rows.map((row) => row.firstElementChild?.firstElementChild?.textContent)).toEqual([
      "posts.signup",
      "posts.lineupLobby(B,3)"
    ]);
    expect(rows[0].querySelector("a")?.getAttribute("href")).toBe(url);
    expect(rows[1].querySelector("a")).toBeNull();
    expect(rows[1].textContent).toContain("post.pending");
  });

  it("drops the lobby letter when the mix runs one lobby", async () => {
    const scope = await mount(
      game({ discord_posts: [post({ slot: "lineup:0:2", kind: "mix.lineup" })] })
    );

    await click(byName(scope, "posts.menu1"));

    expect(document.querySelector('[aria-label="posts.menu"]')?.textContent).toContain(
      "posts.lineup(2)"
    );
  });

  it("deletes a post only after the host confirms", async () => {
    const scope = await mount(
      game({
        discord_posts: [post({ id: 41 }), post({ id: 42, slot: "lineup:0:1", kind: "mix.lineup" })]
      })
    );

    await click(byName(scope, "posts.menu2"));
    await click(document.querySelector('[aria-label="posts.delete(posts.lineup(1))"]'));
    expect(onDeleteDiscordPost).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "posts.deleteDescription(posts.lineup(1))"
    );

    await click(byName(document, "posts.deleteConfirm"));
    expect(onDeleteDiscordPost).toHaveBeenCalledWith(42);
  });

  it("cannot delete a post that is already being deleted", async () => {
    const scope = await mount(game({ discord_posts: [post({ status: "deleting" })] }));

    await click(byName(scope, "posts.menu1"));

    expect(
      document.querySelector('[aria-label="posts.delete(posts.signup)"]')?.hasAttribute("disabled")
    ).toBe(true);
  });
});

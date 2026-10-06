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
const onDeleteDiscordPost = vi.fn();
const onDeleteMix = vi.fn();
const onRename = vi.fn();

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
  props: { canWrite?: boolean; gameLoading?: boolean; canDelete?: boolean } = {}
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
        canDelete={props.canDelete ?? false}
        onDeleteMix={onDeleteMix}
        onRename={onRename}
        onSetSelfService={onSetSelfService}
        onPostSignup={onPostSignup}
        settingLobbyCount={false}
        onLobbyCountChange={onLobbyCountChange}
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
  onDeleteDiscordPost.mockReset();
  onDeleteMix.mockReset();
  onRename.mockReset();
});

// The `⋯` menu: what a host sets once per mix, and the irreversible delete.
// Radix portals it to `document.body`.
function moreTrigger(scope: ParentNode) {
  return scope.querySelector('[aria-label="more"]');
}

function menuItem(text: string) {
  return (
    [...document.querySelectorAll('[role="menuitem"], [role="menuitemradio"]')].find(
      (node) => node.textContent?.trim() === text
    ) ?? null
  );
}

async function chooseMore(scope: ParentNode, item: string) {
  await click(moreTrigger(scope));
  await click(menuItem(item));
}

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
    const scope = await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] }), {
      canWrite: false
    });

    expect(byName(scope, "Add players")).toBeNull();
    expect(moreTrigger(scope)).toBeNull();
    // Reading which mix is open is not a write.
    expect(scope.textContent).toContain("Thursday scrim");
  });

  it("lets a host rename the mix, trimmed, and a viewer not at all", async () => {
    expect((await mount(game(), { canWrite: false })).querySelector('[aria-label="Edit mix name"]')).toBeNull();

    onRename.mockResolvedValue(undefined);
    const scope = await mount(game());
    await click(scope.querySelector('[aria-label="Edit mix name"]'));
    const input = scope.querySelector<HTMLInputElement>('input[aria-label="mix name"]');
    if (!input) throw new Error("Expected the name input");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "  Friday scrim ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await tick();
    });

    expect(onRename).toHaveBeenCalledWith("Friday scrim");
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

  it("opens the access dialog from the more menu", async () => {
    await chooseMore(await mount(game()), "access");

    expect(onOpenAccess).toHaveBeenCalledTimes(1);
  });

  it("opens a second lobby from the more menu", async () => {
    await chooseMore(await mount(game()), "count(2)");

    expect(onLobbyCountChange).toHaveBeenCalledWith(2);
  });

  it("does not re-send the lobby count the mix already runs", async () => {
    await chooseMore(await mount(game()), "count(1)");

    expect(onLobbyCountChange).not.toHaveBeenCalled();
  });

  it("asks before dropping a lobby, because its balance goes with it", async () => {
    await chooseMore(
      await mount(game({ lobby_count: 2, lobbies: [lobbyRow(0), lobbyRow(1)] })),
      "count(1)"
    );

    expect(onLobbyCountChange).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "dropDescription"
    );

    await click(byName(document, "dropConfirm"));
    expect(onLobbyCountChange).toHaveBeenCalledWith(1);
  });

  it("offers delete only to an admin, and only after confirming", async () => {
    await click(moreTrigger(await mount(game())));
    expect(menuItem("delete")).toBeNull();

    await chooseMore(await mount(game(), { canDelete: true }), "delete");
    expect(onDeleteMix).not.toHaveBeenCalled();

    await click(byName(document, "Delete permanently"));
    expect(onDeleteMix).toHaveBeenCalledTimes(1);
  });
});

// Who may sign up, behind the Signup trigger: open or closed first, then where
// an open signup lands. `next-intl` is mocked to echo the key, so every label
// below is the message key rather than the rendered sentence.
function signupTrigger(scope: ParentNode) {
  return scope.querySelector('[aria-label^="signupTrigger"]');
}

async function openSignup(scope: ParentNode) {
  await click(signupTrigger(scope));
  return document;
}

function radio(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll('[role="radio"]')].find(
      (node) => node.textContent?.trim() === name
    ) ?? null
  );
}

describe("PickupMixHeader signup settings", () => {
  it("reads the mix's state on the trigger", async () => {
    const scope = await mount(game({ self_signup: "benched" }));

    expect(signupTrigger(scope)?.getAttribute("aria-label")).toBe(
      "signupTrigger(signupState.benched)"
    );
  });

  it("opens a closed mix into the pool", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "closed" })));

    // Where an open signup lands means nothing while it is closed.
    expect(radio(popover, "signup.pool")).toBeNull();

    await click(radio(popover, "signupOpen"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "pool" });
  });

  it("moves an open signup between the pool and the bench", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "pool" })));

    expect(radio(popover, "signupOpen")?.getAttribute("aria-checked")).toBe("true");
    expect(radio(popover, "signup.pool")?.getAttribute("aria-checked")).toBe("true");
    expect(popover.body.textContent).toContain("signupHint.pool");

    await click(radio(popover, "signup.benched"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "benched" });
  });

  it("closes an open signup, wherever it was landing", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "benched" })));

    await click(radio(popover, "signupState.closed"));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_signup: "closed" });
  });

  it("does not re-send the state the mix is already in", async () => {
    const popover = await openSignup(await mount(game({ self_signup: "benched" })));

    await click(radio(popover, "signupOpen"));

    expect(onSetSelfService).not.toHaveBeenCalled();
  });

  it("writes the role-edit switch on its own", async () => {
    const popover = await openSignup(await mount(game({ self_role_edit: false })));

    await click(popover.querySelector('[aria-label="roleEdit"]'));

    expect(onSetSelfService).toHaveBeenCalledWith({ self_role_edit: true });
  });

  it("shows a viewer who cannot write none of it", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(signupTrigger(scope)).toBeNull();
    expect(discordTrigger(scope)).toBeNull();
  });
});

// Everything the mix has in Discord, behind one trigger that carries the
// signup post's state. The bot answers asynchronously, so this is the only way
// a host learns a post landed -- or why it did not -- and the only way to take
// one down.
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

function discordTrigger(scope: ParentNode) {
  return scope.querySelector('[aria-label^="discord.trigger"]');
}

async function openDiscord(scope: ParentNode) {
  await click(discordTrigger(scope));
  return document;
}

describe("PickupMixHeader Discord signup post", () => {
  it("names the button after what it does: a closed mix is opened into the pool", async () => {
    const menu = await openDiscord(await mount(game({ self_signup: "closed" })));

    expect(menu.body.textContent).toContain("discord.openHint");
    await click(byName(menu, "discord.openAndPost"));

    expect(onPostSignup).toHaveBeenCalledWith("pool");
  });

  it("posts in the mode the mix is in", async () => {
    const menu = await openDiscord(await mount(game({ self_signup: "benched" })));

    await click(byName(menu, "discord.post"));

    expect(onPostSignup).toHaveBeenCalledWith("benched");
  });

  it("calls a post over a live one a re-post, and says it replaces it", async () => {
    const menu = await openDiscord(
      await mount(game({ self_signup: "pool", discord_posts: [post({ status: "posted" })] }))
    );

    expect(byName(menu, "discord.post")).toBeNull();
    expect(menu.body.textContent).toContain("discord.repostHint");
    await click(byName(menu, "discord.repost"));

    expect(onPostSignup).toHaveBeenCalledWith("pool");
  });

  it("offers a plain post again once the last one failed", async () => {
    const menu = await openDiscord(
      await mount(game({ self_signup: "pool", discord_posts: [post({ status: "failed" })] }))
    );

    expect(byName(menu, "discord.post")).not.toBeNull();
  });

  it("says why there is no post button without a mix channel", async () => {
    const menu = await openDiscord(
      await mount(
        game({
          self_signup: "pool",
          settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null }
        })
      )
    );

    expect(byName(menu, "discord.post")).toBeNull();
    expect(menu.body.textContent).toContain("noChannel");
  });
});

describe("PickupMixHeader Discord post status", () => {
  async function status(scope: ParentNode) {
    return (await openDiscord(scope)).querySelector('[role="status"]');
  }

  it("says there is no post yet", async () => {
    const scope = await mount(game({ discord_posts: [] }));

    expect(discordTrigger(scope)?.getAttribute("aria-label")).toBe("discord.trigger(post.none)");
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

    expect(discordTrigger(scope)?.getAttribute("aria-label")).toBe("discord.trigger(post.posted)");
    const link = (await status(scope))?.querySelector("a");
    expect(link?.getAttribute("href")).toBe(url);
    expect(link?.getAttribute("target")).toBe("_blank");
    expect(link?.textContent).toBe("post.posted");
  });

  it("exposes Discord's refusal on a failed post", async () => {
    const scope = await mount(
      game({ discord_posts: [post({ status: "failed", error: "Missing Permissions" })] })
    );

    expect(discordTrigger(scope)?.getAttribute("aria-label")).toBe("discord.trigger(post.failed)");
    expect((await status(scope))?.textContent).toContain("Missing Permissions. post.failedHint");
  });

  it("tells the host a lost post never reached Discord", async () => {
    const region = await status(await mount(game({ discord_posts: [post({ status: "lost" })] })));

    expect(region?.textContent).toContain("post.lost");
    expect(region?.textContent).toContain("post.lostHint");
  });
});

describe("PickupMixHeader Discord posts list", () => {
  const twoLobbies = { lobby_count: 2 as const, lobbies: [lobbyRow(0), lobbyRow(1)] };
  const list = () => document.querySelector('[aria-label="discord.allPosts"]');

  it("is not offered while the mix has no posts", async () => {
    await openDiscord(await mount(game({ discord_posts: [] })));

    expect(list()).toBeNull();
  });

  it("lists every post, lineup cards by lobby and game", async () => {
    const url = "https://discord.com/channels/1/2/3";
    await openDiscord(
      await mount(
        game({
          ...twoLobbies,
          discord_posts: [
            post({ id: 1, url }),
            post({ id: 2, slot: "lineup:1:3", kind: "mix.lineup", status: "pending" })
          ]
        })
      )
    );

    const rows = [...(list()?.querySelectorAll("li") ?? [])];
    expect(rows.map((row) => row.firstElementChild?.firstElementChild?.textContent)).toEqual([
      "posts.signup",
      "posts.lineupLobby(B,3)"
    ]);
    expect(rows[0].querySelector("a")?.getAttribute("href")).toBe(url);
    expect(rows[1].querySelector("a")).toBeNull();
    expect(rows[1].textContent).toContain("post.pending");
  });

  it("drops the lobby letter when the mix runs one lobby", async () => {
    await openDiscord(
      await mount(game({ discord_posts: [post({ slot: "lineup:0:2", kind: "mix.lineup" })] }))
    );

    expect(list()?.textContent).toContain("posts.lineup(2)");
  });

  it("deletes a post only after the host confirms", async () => {
    await openDiscord(
      await mount(
        game({
          discord_posts: [post({ id: 41 }), post({ id: 42, slot: "lineup:0:1", kind: "mix.lineup" })]
        })
      )
    );

    await click(document.querySelector('[aria-label="posts.delete(posts.lineup(1))"]'));
    expect(onDeleteDiscordPost).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "posts.deleteDescription(posts.lineup(1))"
    );

    await click(byName(document, "posts.deleteConfirm"));
    expect(onDeleteDiscordPost).toHaveBeenCalledWith(42);
  });

  it("cannot delete a post that is already being deleted", async () => {
    await openDiscord(await mount(game({ discord_posts: [post({ status: "deleting" })] })));

    expect(
      document.querySelector('[aria-label="posts.delete(posts.signup)"]')?.hasAttribute("disabled")
    ).toBe(true);
  });
});

// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DraftBoard, DraftPlayer } from "@/types/draft.types";
import type { UserProfile } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { PlayerProfileDialog } from "./PlayerProfileDialog";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Message keys, not copy: every assertion below is about WHICH fact reaches the
// screen, so the key path is the most legible witness of it.
vi.mock("next-intl", () => ({
  useLocale: () => "en",
  useTranslations: () => (key: string, values?: Record<string, unknown>) =>
    values ? `${key}:${JSON.stringify(values)}` : key
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

// The dialog is handed its grid explicitly; the ambient workspace grid must
// never be the one a rank resolves against.
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({ tiers: [] })
}));

const getUserProfile = vi.fn();
vi.mock("@/services/user.service", () => ({
  default: { getUserProfile: (...args: unknown[]) => getUserProfile(...args) }
}));

function player(overrides: Partial<DraftPlayer> = {}): DraftPlayer {
  return {
    id: 7,
    session_id: 1,
    registration_id: 70,
    user_id: null,
    battle_tag: "Ana#1234",
    primary_role: "support",
    sub_role: null,
    is_flex: false,
    effective_rank: 3000,
    status: "available",
    is_captain: false,
    drafted_by_team_id: null,
    secondary_roles: [],
    role_ranks: {},
    role_sources: {},
    role_top_heroes: {},
    notes: null,
    custom_fields: [],
    version: 1,
    ...overrides
  };
}

// Two tiers so a rank maps to a division a test can tell apart. An empty grid
// resolves every rank to null, which would make a rank assertion vacuous.
const GRID: DivisionGrid = {
  tiers: [
    {
      slug: "high",
      number: 9,
      name: "High",
      sort_order: 0,
      rank_min: 3000,
      rank_max: 3999,
      icon_url: "/high.png"
    },
    {
      slug: "low",
      number: 4,
      name: "Low",
      sort_order: 1,
      rank_min: 2000,
      rank_max: 2999,
      icon_url: "/low.png"
    }
  ]
};

const EMPTY_GRID: DivisionGrid = { tiers: [] };

const BOARD = {
  teams: [{ id: 3, name: "Team Rocket" }],
  picks: [{ picked_player_id: 7, target_role: "tank" }]
} as unknown as DraftBoard;

function profile(overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    tournaments_count: 12,
    tournaments_won: 3,
    maps_total: 50,
    maps_won: 30,
    avg_closeness: null,
    avg_placement: 4.25,
    avg_playoff_placement: null,
    avg_group_placement: null,
    most_played_hero: null as never,
    roles: [
      {
        role: "Support",
        tournaments: 10,
        maps_won: 25,
        maps: 40,
        division: 9,
        division_grid_version: null
      }
    ],
    hero_statistics: [
      {
        hero: { id: 1, name: "Ana", slug: "ana", image_path: "/heroes/ana.png" } as never,
        playtime: 0.42
      }
    ],
    tournaments: [
      { id: 2, name: "Winter Cup", is_league: false, division_grid_version: null },
      { id: 9, name: "Spring Cup", is_league: false, division_grid_version: null }
    ],
    ...overrides
  };
}

async function mount(node: ReactNode) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  await act(async () => {
    root.render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  });
  await settle();
  // Radix Dialog portals outside the container.
  return document.body;
}

async function settle() {
  for (let turn = 0; turn < 6; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

function open(subject: DraftPlayer, divisionGrid: DivisionGrid = EMPTY_GRID) {
  return mount(
    <PlayerProfileDialog
      player={subject}
      open
      onOpenChange={() => {}}
      board={BOARD}
      divisionGrid={divisionGrid}
    />
  );
}

function tabTrigger(key: string): HTMLElement | undefined {
  return Array.from(document.body.querySelectorAll<HTMLElement>("[role='tab']")).find(
    (node) => node.textContent?.trim() === key
  );
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0 }));
    element.click();
  });
  await settle();
}

beforeEach(() => {
  document.body.innerHTML = "";
  getUserProfile.mockReset().mockResolvedValue(profile());
});

describe("player profile registration answers", () => {
  it("renders every public answer with its label, and a checkbox no as a word", async () => {
    const body = await open(
      player({
        custom_fields: [
          { key: "vk", label: "VK profile", type: "url", value: "https://vk.com/ana" },
          { key: "shift", label: "Preferred shift", type: "select", value: "Evening" },
          { key: "rules", label: "Rules read", type: "checkbox", value: false }
        ]
      })
    );

    const html = body.innerHTML;
    expect(html).toContain("VK profile");
    expect(html).toContain("https://vk.com/ana");
    expect(html).toContain("Preferred shift");
    expect(html).toContain("Evening");
    // A checkbox "no" is an answer, and it renders as a word rather than the
    // raw `false` a plain String() would produce.
    expect(html).toContain("Rules read");
    expect(html).toContain("customFieldNo");
    expect(html).not.toContain("false<");
  });

  it("says so when the player answered nothing", async () => {
    const body = await open(player());

    expect(body.innerHTML).toContain("profile.noAnswers");
  });

  it("names the team that drafted the player, on the role they were drafted for", async () => {
    const body = await open(player({ status: "picked", drafted_by_team_id: 3 }));

    expect(body.innerHTML).toContain('profile.draftedBy:{"team":"Team Rocket"}');
    // `target_role` on the pick wins over the player's primary role.
    expect(body.innerHTML).toContain("roles.tank");
  });
});

describe("player profile role ranks", () => {
  // Ranked on support only, but flex — so tank is listed without a rating.
  const flexPlayer = player({
    primary_role: "support",
    secondary_roles: ["tank"],
    is_flex: true,
    effective_rank: 2814,
    role_ranks: { support: 2814 },
    role_sources: { support: "registration" }
  });

  it("shows no rank on a role the player has none on, not the primary's", async () => {
    const body = await open(flexPlayer, GRID);

    const rows = Array.from(body.querySelectorAll("li[title]"));
    const support = rows.find((row) => row.getAttribute("title")?.includes("roles.support"));
    const tank = rows.find((row) => row.getAttribute("title")?.includes("roles.tank"));

    expect(support?.textContent).toContain("2814 SR");
    // Lending support's number to tank would invent a rating a captain then
    // picks on; the unranked role carries the em-dash instead.
    expect(tank?.textContent).not.toContain("SR");
    expect(tank?.textContent).toContain("—");
  });

  it("puts the rank the server resolved for this draft in the header, not the maximum", async () => {
    // A support main: 2814 on support, 3900 on damage. The header renders
    // `effective_rank` — the ONE rank the roster engine resolved for this draft
    // — or it advertises a 3900 support.
    const body = await open(
      player({
        primary_role: "support",
        secondary_roles: ["damage"],
        effective_rank: 2814,
        role_ranks: { support: 2814, damage: 3900 }
      }),
      GRID
    );

    // The header crest is the first image in the dialog; the role rows follow.
    const crests = Array.from(body.querySelectorAll("img"));
    expect(crests[0]?.getAttribute("alt")).toBe("Low");
    // The rows stay per-role: both ranks are still readable.
    expect(body.textContent).toContain("2814 SR");
    expect(body.textContent).toContain("3900 SR");
  });

  it("labels a rank the registration did not declare with its source", async () => {
    // An organizer has to be able to tell an inherited or Overwatch-derived
    // rank from one the player typed in.
    const body = await open(
      player({ role_ranks: { support: 2814 }, role_sources: { support: "ow" } }),
      GRID
    );

    expect(body.innerHTML).toContain("rankSourceShort.ow");
    expect(body.innerHTML).toContain("rankSource.ow");
  });

  it("shows no role at all for a player left without one", async () => {
    const body = await open(player({ primary_role: null, secondary_roles: [] }), GRID);

    expect(body.innerHTML).toContain("noRole");
    expect(body.innerHTML).toContain("noRoleHint");
    expect(body.querySelectorAll("li[title]")).toHaveLength(0);
  });
});

describe("player profile site statistics", () => {
  it("offers no stats tab for a player with no site account", async () => {
    const body = await open(player({ user_id: null }));

    expect(tabTrigger("profile.tabStats")).toBeUndefined();
    expect(body.innerHTML).toContain("profile.tabRegistration");
    expect(getUserProfile).not.toHaveBeenCalled();
  });

  it("fetches the profile only once the stats tab is opened", async () => {
    const body = await open(player({ user_id: 42 }));

    // Registration is the default tab, so nothing is fetched on open.
    expect(getUserProfile).not.toHaveBeenCalled();

    const trigger = tabTrigger("profile.tabStats");
    expect(trigger).toBeDefined();
    await click(trigger as HTMLElement);

    expect(getUserProfile).toHaveBeenCalledWith(42);
    // 30 of 50 maps won — a share, not a raw count, and guarded so a player
    // with no map played reads as unknown rather than 0%.
    expect(body.textContent).toContain("60%");
    expect(body.textContent).toContain("4.3");
    expect(body.textContent).toContain("Ana");
    // Most recent first, and only three of them.
    expect(body.textContent).toContain("Spring Cup");
  });

  it("offers a retry when the profile read fails", async () => {
    getUserProfile.mockRejectedValue(new Error("boom"));
    const body = await open(player({ user_id: 42 }));

    await click(tabTrigger("profile.tabStats") as HTMLElement);

    expect(body.innerHTML).toContain("profile.stats.error");
    expect(body.innerHTML).toContain("profile.stats.retry");
  });
});

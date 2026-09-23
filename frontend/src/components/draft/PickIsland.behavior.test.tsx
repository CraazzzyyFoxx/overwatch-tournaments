// @vitest-environment happy-dom
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DraftMutations } from "@/hooks/useDraftData";
import type { DraftGating } from "@/lib/draft/logic";
import { buildTeamViews, type RoomSelection } from "@/lib/draft/room-model";
import type { RosterShape } from "@/lib/roster/shape";
import type { DraftBoard, DraftPick, DraftPlayer, DraftTeam } from "@/types/draft.types";
import type { UserDraftCard } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { PickIsland } from "./PickIsland";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// Message keys, not copy: every assertion is about WHICH fact reaches the screen.
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

// The island is handed its grid; the ambient workspace grid must never be the one a rank resolves against.
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({ tiers: [] })
}));

const getDraftCard = vi.fn();
vi.mock("@/hooks/useDraftData", () => ({
  useDraftPlayerCardQuery: (userId: number | null) =>
    useQuery({
      queryKey: ["card", userId],
      queryFn: () => getDraftCard(userId),
      enabled: userId != null
    })
}));

const notifySuccess = vi.fn();
const notifyApiError = vi.fn();
vi.mock("@/lib/notify", () => ({
  notify: {
    success: (...args: unknown[]) => notifySuccess(...args),
    apiError: (...args: unknown[]) => notifyApiError(...args)
  }
}));

const SHAPE: RosterShape = {
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 4,
  source: null
};

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
    role_ranks: { support: 3000 },
    role_sources: {},
    role_top_heroes: {},
    role_sub_roles: {},
    notes: null,
    custom_fields: [],
    version: 1,
    ...overrides
  };
}

const team = (id: number, name: string): DraftTeam => ({
  id,
  session_id: 1,
  captain_user_id: null,
  captain_auth_user_id: null,
  name,
  draft_position: id,
  exported_team_id: null
});

const CURRENT: DraftPick = {
  id: 11,
  session_id: 1,
  overall_no: 1,
  round_no: 1,
  pick_in_round: 1,
  draft_team_id: 1,
  target_role: null,
  target_rank_value: null,
  status: "on_clock",
  picked_player_id: null,
  picked_by_user_id: null,
  is_autopick: false,
  is_admin_override: false,
  clock_started_at: null,
  clock_expires_at: null,
  overtime_started_at: null,
  version: 4
};

function board(players: DraftPlayer[], sessionPatch: Partial<DraftBoard["session"]> = {}): DraftBoard {
  return {
    session: {
      id: 1, tournament_id: 1, workspace_id: 1, status: "live", blocked_reason: null, format: "snake",
      rounds: 4, pick_time_seconds: 45, overtime_seconds: 0, roster_shape: SHAPE, current_pick_id: CURRENT.id,
      pool_source: "manual", source_balance_id: null, autopick_strategy: "best_fit", allow_admin_override: true,
      exported_at: null, export_status: null, settings_json: {}, version: 1, created_at: null,
      ...sessionPatch
    },
    teams: [team(1, "Team Rocket"), team(2, "Blue")],
    picks: [CURRENT, { ...CURRENT, id: 12, overall_no: 2, pick_in_round: 2, draft_team_id: 2, status: "upcoming" }],
    players,
    current_pick: CURRENT,
    server_time: "2026-09-23T00:00:00Z",
    last_event_id: null
  };
}

const GRID: DivisionGrid = {
  tiers: [
    { slug: "high", number: 9, name: "High", sort_order: 0, rank_min: 3000, rank_max: 3999, icon_url: "/high.png" },
    { slug: "low", number: 4, name: "Low", sort_order: 1, rank_min: 2000, rank_max: 2999, icon_url: "/low.png" }
  ]
};

const SPECTATOR: DraftGating = { myTeamId: null, isCaptain: false, isAdmin: false, isMyPick: false, isSpectator: true };
const CAPTAIN_ON_TURN: DraftGating = { myTeamId: 1, isCaptain: true, isAdmin: false, isMyPick: true, isSpectator: false };
const CAPTAIN_WAITING: DraftGating = { myTeamId: 2, isCaptain: true, isAdmin: false, isMyPick: false, isSpectator: false };
const ADMIN: DraftGating = { myTeamId: null, isCaptain: false, isAdmin: true, isMyPick: false, isSpectator: false };

function mutations() {
  return {
    makePick: { mutate: vi.fn(), isPending: false },
    override: { mutate: vi.fn(), isPending: false }
  };
}

interface Setup {
  subject?: DraftPlayer;
  gating?: DraftGating;
  actingTeamId?: number | null;
  selection?: RoomSelection | null;
  canConfirm?: boolean;
  overrideMode?: boolean;
  sessionPatch?: Partial<DraftBoard["session"]>;
  queue?: boolean;
  /** Everyone else on the board (rostered players shape the acting team's open slots). */
  others?: DraftPlayer[];
}

async function open(setup: Setup = {}) {
  const subject = setup.subject ?? player();
  const b = board([subject, ...(setup.others ?? [])], setup.sessionPatch);
  const views = buildTeamViews(b);
  const m = mutations();
  const onSelectRole = vi.fn();
  const onPicked = vi.fn();
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <PickIsland
          board={b}
          gating={setup.gating ?? SPECTATOR}
          player={subject}
          selection={setup.selection ?? null}
          onSelectRole={onSelectRole}
          onClose={() => {}}
          actingTeam={setup.actingTeamId != null ? (views.get(setup.actingTeamId) ?? null) : null}
          overrideMode={setup.overrideMode ?? false}
          showTargets={false}
          target="mine"
          onTargetChange={() => {}}
          canConfirm={setup.canConfirm ?? false}
          connectionState="connected"
          mutations={m as unknown as DraftMutations}
          autopickPreview={null}
          queue={setup.queue ? { ids: [], toggle: vi.fn(), move: vi.fn() } : null}
          divisionGrid={GRID}
          onPicked={onPicked}
        />
      </QueryClientProvider>
    );
  });
  await settle();
  return { body: document.body, mutations: m, onSelectRole, onPicked };
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

async function click(element: Element) {
  await act(async () => {
    (element as HTMLElement).click();
  });
  await settle();
}

async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function buttonStartingWith(prefix: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll<HTMLButtonElement>("button")).find((node) =>
    node.textContent?.trim().startsWith(prefix)
  );
}

function tile(role: string): HTMLElement | null {
  return document.body.querySelector<HTMLElement>(`[role='group'] [title^='roles.${role}']`);
}

function card(overrides: Partial<UserDraftCard> = {}): UserDraftCard {
  return {
    tournaments: 12,
    tournaments_won: 1,
    maps: 50,
    maps_won: 30,
    maps_lost: 20,
    mvp_maps: 4,
    best_placement: 1,
    avg_placement: 4.4,
    roles: [{ role: "support", maps: 40, maps_won: 26 }],
    heroes: [
      { hero: { id: 1, slug: "ana", name: "Ana", image_path: null } as never, role: "support", maps: 30, maps_won: 20 }
    ],
    recent_tournaments: [
      { id: 9, name: "Spring Cup", date: "2026-05-01", role: "support", rank: 3100, placement: 2, teams_count: 16 },
      { id: 2, name: "Winter Cup", date: "2026-01-01", role: "support", rank: 2900, placement: 5, teams_count: 16 }
    ],
    ...overrides
  };
}

beforeEach(() => {
  document.body.innerHTML = "";
  getDraftCard.mockReset().mockResolvedValue(card());
  notifySuccess.mockReset();
  notifyApiError.mockReset();
});

describe("spectator", () => {
  it("gets the card only: no action footer, no heart, no target toggle, role chips instead of buttons", async () => {
    const { body } = await open();

    expect(body.querySelector("[role='dialog']")?.getAttribute("aria-label")).toBe(
      'island.aria:{"player":"Ana#1234"}'
    );
    expect(buttonStartingWith("island.action")).toBeUndefined();
    expect(body.querySelector("[aria-label='island.queue.add']")).toBeNull();
    expect(body.querySelector("[role='radiogroup']")).toBeNull();
    expect(tile("support")?.tagName).toBe("DIV");
  });
});

describe("captain", () => {
  it("confirms only with canConfirm, sending the pick version and the chosen role", async () => {
    const selection = { playerId: 7, role: "support" as const };
    const blocked = await open({ gating: CAPTAIN_ON_TURN, actingTeamId: 1, selection, canConfirm: false });
    const disabledButton = blocked.body.querySelector<HTMLButtonElement>("[data-draft-confirm]");
    expect(disabledButton?.disabled).toBe(true);

    document.body.innerHTML = "";
    const { body, mutations: m, onPicked } = await open({
      gating: CAPTAIN_ON_TURN,
      actingTeamId: 1,
      selection,
      canConfirm: true
    });
    const confirm = body.querySelector<HTMLButtonElement>("[data-draft-confirm]");
    expect(confirm?.disabled).toBe(false);
    await click(confirm!);

    expect(m.makePick.mutate).toHaveBeenCalledWith(
      { pickId: 11, playerId: 7, version: 4, role: "support" },
      expect.anything()
    );
    await act(async () => m.makePick.mutate.mock.calls[0][1].onSuccess());
    expect(notifySuccess).toHaveBeenCalledWith('pickSuccess:{"player":"Ana#1234"}');
    expect(onPicked).toHaveBeenCalled();
    expect(body.querySelector("[aria-live='polite']")?.textContent).toBe('pickSuccess:{"player":"Ana#1234"}');
  });

  it("toasts an api error instead of closing the card", async () => {
    const { mutations: m, onPicked } = await open({
      gating: CAPTAIN_ON_TURN,
      actingTeamId: 1,
      selection: { playerId: 7, role: "support" },
      canConfirm: true
    });
    await click(document.body.querySelector("[data-draft-confirm]")!);
    const error = new Error("stale");
    await act(async () => m.makePick.mutate.mock.calls[0][1].onError(error));

    expect(notifyApiError).toHaveBeenCalledWith(error);
    expect(onPicked).not.toHaveBeenCalled();
  });

  it("off turn waits, but the role tiles still prepare a selection", async () => {
    const { body, onSelectRole } = await open({ gating: CAPTAIN_WAITING, actingTeamId: 2, queue: true });

    const wait = buttonStartingWith("island.action.wait");
    expect(wait?.disabled).toBe(true);
    expect(body.querySelector("[data-draft-confirm]")).toBeNull();
    expect(body.querySelector("[aria-label='island.queue.add']")).not.toBeNull();

    await click(tile("support")!);
    expect(onSelectRole).toHaveBeenCalledWith("support");
  });

  it("does not select a role the team has no slot for", async () => {
    // Team 2 already holds a tank: the only tank slot of the shape is gone.
    const { onSelectRole } = await open({
      gating: CAPTAIN_WAITING,
      actingTeamId: 2,
      subject: player({ secondary_roles: ["tank"], role_ranks: { support: 3000, tank: 2500 } }),
      others: [
        player({ id: 8, primary_role: "tank", status: "picked", drafted_by_team_id: 2, role_ranks: { tank: 3000 } })
      ]
    });

    const tankTile = tile("tank")!;
    expect(tankTile.getAttribute("aria-disabled")).toBe("true");
    expect(tankTile.getAttribute("title")).toContain("island.tile.noSlot");
    await click(tankTile);
    expect(onSelectRole).not.toHaveBeenCalled();
    // The seatable role on the same card still selects.
    await click(tile("support")!);
    expect(onSelectRole).toHaveBeenCalledWith("support");
  });
});

describe("admin override", () => {
  it("stays disabled until a reason is typed, and sends the reason with the override", async () => {
    const { body, mutations: m } = await open({
      gating: ADMIN,
      actingTeamId: 1,
      overrideMode: true,
      selection: { playerId: 7, role: "support" }
    });

    const apply = buttonStartingWith("island.action.overrideRole")!;
    expect(apply.disabled).toBe(true);

    await type(body.querySelector<HTMLInputElement>("input[aria-label='island.overrideNoteLabel']")!, "  captain AFK ");
    expect(apply.disabled).toBe(false);
    await click(apply);

    expect(m.override.mutate).toHaveBeenCalledWith(
      { pickId: 11, playerId: 7, version: 4, role: "support", note: "captain AFK" },
      expect.anything()
    );
  });

  it("explains instead of offering the override when the session disallows it", async () => {
    const { body } = await open({
      gating: ADMIN,
      actingTeamId: 1,
      overrideMode: true,
      selection: { playerId: 7, role: "support" },
      sessionPatch: { allow_admin_override: false }
    });

    expect(body.innerHTML).toContain("overrideDisabled");
    expect(buttonStartingWith("island.action.override")).toBeUndefined();
    expect(body.querySelector("input[aria-label='island.overrideNoteLabel']")).toBeNull();
  });
});

describe("role tiles", () => {
  it("shows no rank on a role the player has none on, not the primary's", async () => {
    await open({ subject: player({ secondary_roles: ["tank"], is_flex: true, role_ranks: { support: 2814 } }) });

    expect(tile("support")?.textContent).toContain("2814");
    expect(tile("tank")?.textContent).not.toContain("2814");
    expect(tile("tank")?.textContent).toContain("—");
  });

  it("puts the rank the server resolved for this draft in the header crest", async () => {
    const { body } = await open({
      subject: player({ secondary_roles: ["damage"], effective_rank: 2814, role_ranks: { support: 2814, damage: 3900 } })
    });

    expect(body.querySelector("[role='dialog'] img")?.getAttribute("alt")).toBe("Low");
  });

  it("labels a rank the registration did not declare with its source", async () => {
    const { body } = await open({ subject: player({ role_ranks: { support: 2814 }, role_sources: { support: "ow" } }) });

    expect(body.innerHTML).toContain("rankSourceShort.ow");
    expect(body.innerHTML).toContain("rankSource.ow");
  });

  it("explains a player left without any role", async () => {
    const { body } = await open({ subject: player({ primary_role: null, secondary_roles: [] }) });

    expect(body.innerHTML).toContain("noRoleHint");
    expect(tile("support")).toBeNull();
  });
});

describe("registration answers", () => {
  it("renders every public answer behind the collapsed section, a checkbox no as a word", async () => {
    const { body } = await open({
      subject: player({
        notes: "Plays evenings",
        custom_fields: [
          { key: "vk", label: "VK profile", type: "url", value: "https://vk.com/ana" },
          { key: "rules", label: "Rules read", type: "checkbox", value: false }
        ]
      })
    });
    expect(body.innerHTML).not.toContain("VK profile");

    await click(buttonStartingWith("island.registration.heading")!);

    expect(body.innerHTML).toContain("VK profile");
    expect(body.innerHTML).toContain("https://vk.com/ana");
    expect(body.innerHTML).toContain("Plays evenings");
    expect(body.innerHTML).toContain("customFieldNo");
    expect(body.innerHTML).not.toContain("false<");
  });
});

describe("career stats", () => {
  it("fetches nothing and shows no stats for a player without an account", async () => {
    const { body } = await open({ subject: player({ user_id: null }) });

    expect(getDraftCard).not.toHaveBeenCalled();
    expect(body.innerHTML).not.toContain("island.stats.tournaments");
    expect(body.innerHTML).not.toContain("island.firstTournament");
  });

  it("shows the winrate verdict, per-role maps and the recent tournaments", async () => {
    const { body } = await open({ subject: player({ user_id: 42 }) });

    expect(getDraftCard).toHaveBeenCalledWith(42);
    expect(body.textContent).toContain("60%");
    expect(body.textContent).toContain("30–20");
    // Newest 3100 against oldest 2900.
    expect(body.textContent).toContain("+200");
    expect(tile("support")?.textContent).toContain("65%");
    expect(body.textContent).toContain("Spring Cup");
  });

  it("hides the winrate under ten maps", async () => {
    getDraftCard.mockResolvedValue(card({ maps: 6, maps_won: 5, maps_lost: 1 }));
    const { body } = await open({ subject: player({ user_id: 42 }) });

    expect(body.textContent).not.toContain("83%");
    expect(body.innerHTML).toContain("island.stats.lowSample");
  });

  it("says it is the player's first tournament when there is no history", async () => {
    getDraftCard.mockResolvedValue(card({ tournaments: 0, maps: 0, heroes: [], recent_tournaments: [], roles: [] }));
    const { body } = await open({ subject: player({ user_id: 42 }) });

    expect(body.innerHTML).toContain("island.firstTournament");
  });

  it("offers a retry when the card read fails", async () => {
    getDraftCard.mockRejectedValue(new Error("boom"));
    const { body } = await open({ subject: player({ user_id: 42 }) });

    expect(body.innerHTML).toContain("profile.stats.error");
    expect(body.innerHTML).toContain("profile.stats.retry");
  });
});

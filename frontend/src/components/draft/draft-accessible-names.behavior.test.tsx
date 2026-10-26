// @vitest-environment happy-dom
//
// What a screen reader announces in the draft room, read through the real
// catalogs (the sibling tests echo message keys, which hides the copy itself):
// every control a captain can reach names a different thing.
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import ru from "@/i18n/messages/ru.json";
import type { DraftMutations } from "@/hooks/useDraftData";
import type { DraftGating } from "@/lib/draft/logic";
import { buildTeamViews, filterSortTeams } from "@/lib/draft/room-model";
import type { RosterShape } from "@/lib/roster/shape";
import { DEADLOCK_METADATA, LOL_METADATA, OW_METADATA } from "@/test/discipline-metadata";
import type { DraftBoard, DraftPick, DraftPlayer, DraftSession } from "@/types/draft.types";

import { PickIsland } from "./PickIsland";
import { TeamRosters } from "./TeamRosters";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));
vi.mock("@/hooks/useCurrentWorkspace", () => ({ useDivisionGrid: () => ({ tiers: [] }) }));
vi.mock("@/hooks/useDraftData", () => ({
  useDraftPlayerCardQuery: (userId: number | null) =>
    useQuery({ queryKey: ["card", userId], queryFn: () => null, enabled: false })
}));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));

const OW_SHAPE: RosterShape = {
  dimension: "player_role",
  slots: { tank: 1, damage: 2, support: 2 },
  team_size: 5,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 5,
  source: null
};
const ONE_ROLE_SHAPE: RosterShape = {
  dimension: "agent",
  slots: { agent: 6 },
  team_size: 6,
  flex_slots: 0,
  has_role_slots: true,
  draft_rounds: 5,
  source: null
};

const ana: DraftPlayer = {
  id: 7,
  session_id: 1,
  registration_id: 70,
  user_id: null,
  identity: { provider: "battlenet", handle: "Ana#1234" },
  player_name: null,
  primary_role: { dimension: "player_role", role: "support" },
  is_flex: false,
  effective_rank: 3000,
  status: "available",
  is_captain: false,
  drafted_by_team_id: null,
  secondary_roles: [{ dimension: "player_role", role: "damage" }],
  role_ranks: { support: 3000, damage: 2800 },
  role_sources: {},
  role_top_characters: {},
  role_sub_roles: {},
  notes: null,
  custom_fields: [],
  version: 1
};

const onClock: DraftPick = {
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

function board(shape: RosterShape, players: DraftPlayer[]): DraftBoard {
  const team = (id: number, name: string) => ({
    id,
    session_id: 1,
    captain_user_id: null,
    captain_auth_user_id: null,
    name,
    draft_position: id,
    exported_team_id: null
  });
  return {
    session: {
      id: 1, tournament_id: 1, custom_game_id: null, lobby_index: null, workspace_id: 1, discipline: "overwatch", status: "live", blocked_reason: null,
      format: "snake", rounds: 5, pick_time_seconds: 45, overtime_seconds: 0, roster_shape: shape,
      current_pick_id: onClock.id, pool_source: "manual", source_balance_id: null, autopick_strategy: "best_fit",
      allow_admin_override: true, exported_at: null, export_status: null, settings_json: {}, version: 1, created_at: null
    } as unknown as DraftSession,
    teams: [team(1, "Team Rocket"), team(2, "Blue")],
    picks: [onClock],
    players,
    current_pick: onClock,
    last_event_id: null
  };
}

const CAPTAIN_ON_TURN: DraftGating = { myTeamId: 1, isCaptain: true, isAdmin: false, isMyPick: true, isSpectator: false };

/** The open player card, rendered through a real catalog; the caller reads it, then unmounts. */
async function renderCard(
  messages: typeof en,
  locale: string,
  { shape, player, role, ontology }: { shape: RosterShape; player: DraftPlayer; role: string; ontology: typeof OW_METADATA }
) {
  const b = board(shape, [player]);
  const views = buildTeamViews(b);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
        <QueryClientProvider client={new QueryClient()}>
          <PickIsland
            board={b}
            gating={CAPTAIN_ON_TURN}
            player={player}
            selection={{ playerId: player.id, role }}
            onSelectRole={() => {}}
            onClose={() => {}}
            actingTeam={views.get(1) ?? null}
            overrideMode={false}
            showTargets={false}
            target="mine"
            onTargetChange={() => {}}
            canConfirm
            connectionState="connected"
            mutations={{ makePick: { mutate: vi.fn(), isPending: false }, override: { mutate: vi.fn(), isPending: false } } as unknown as DraftMutations}
            autopickPreview={null}
            queue={null}
            divisionGrid={{ tiers: [] }}
            ontology={ontology}
            onPicked={() => {}}
          />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    }
  };
}

/** Every button's accessible name in the card: its `aria-label`, else its text. */
async function cardButtonNames(
  messages: typeof en,
  locale: string,
  setup: { shape: RosterShape; player: DraftPlayer; role: string; ontology: typeof OW_METADATA }
) {
  const { container, unmount } = await renderCard(messages, locale, setup);
  const names = [...container.querySelectorAll("button")].map(
    (button) => button.getAttribute("aria-label") ?? (button.textContent ?? "").trim()
  );
  unmount();
  return names;
}

function expectDistinct(names: string[]) {
  const folded = names.map((name) => name.toLocaleLowerCase());
  expect(new Set(folded).size, names.join(" | ")).toBe(folded.length);
}

describe("the player card", () => {
  it.each([
    ["en", en],
    ["ru", ru]
  ] as const)("tells choosing a role apart from confirming the pick (%s)", async (locale, messages) => {
    const names = await cardButtonNames(messages, locale, { shape: OW_SHAPE, player: ana, role: "support", ontology: OW_METADATA });

    expectDistinct(names);
    if (locale === "en") {
      expect(names).toContain("Select Ana#1234 as Support");
      expect(names).toContain("Select Ana#1234 as Damage");
      expect(names).toContain("Pick Ana#1234 as support");
    }
  });

  it("does the same in a one-role game, where neither name carries a role", async () => {
    const agent = { dimension: "agent", role: "agent" };
    const player = { ...ana, primary_role: agent, secondary_roles: [], role_ranks: { agent: 3000 } };
    const names = await cardButtonNames(en, "en", { shape: ONE_ROLE_SHAPE, player, role: "agent", ontology: DEADLOCK_METADATA });

    expectDistinct(names);
    expect(names).toContain("Select Ana#1234");
    expect(names).toContain("Pick Ana#1234");
  });
});

describe("the role tiles", () => {
  it.each([
    ["en", en, "Host's rank", "HOST"],
    ["ru", ru, "Ранг хоста", "ХОСТ"]
  ] as const)("says a mix rank comes from the host's book (%s)", async (locale, messages, label, short) => {
    const player = { ...ana, role_sources: { support: "author" as const } };
    const { container, unmount } = await renderCard(messages, locale, { shape: OW_SHAPE, player, role: "support", ontology: OW_METADATA });
    const badge = [...container.querySelectorAll("span[title]")].find((span) => span.getAttribute("title") === label);

    expect(badge?.textContent).toBe(short);
    unmount();
  });
});

describe("the pool", () => {
  it.each([
    ["en", en],
    ["ru", ru]
  ] as const)("names a pool cell differently from the card's confirm (%s)", (locale, messages) => {
    const t = createTranslator({ locale, messages, namespace: "draftRedesign" });
    const select = t("pickAs", { player: "Ana#1234", role: "Support" }).toLocaleLowerCase();
    const selectOnly = t("island.tile.selectPlayer", { player: "Ana#1234" }).toLocaleLowerCase();

    expect(select).not.toBe(t("island.action.pickRole", { player: "Ana#1234", role: "support" }).toLocaleLowerCase());
    expect(selectOnly).not.toBe(t("island.action.pickPlayer", { player: "Ana#1234" }).toLocaleLowerCase());
  });
});

describe("the team filters", () => {
  function needNames(messages: typeof en, locale: string, shape: RosterShape, ontology: typeof OW_METADATA) {
    const b = { ...board(shape, []), picks: [], current_pick: null };
    const teamViews = buildTeamViews(b);
    const html = renderToStaticMarkup(
      <NextIntlClientProvider locale={locale} messages={messages} timeZone="UTC">
        <TeamRosters
          board={b}
          teamViews={teamViews}
          teams={filterSortTeams(b, teamViews, { filter: "all", sort: "order", followed: new Set(), myTeamId: null })}
          filter="all"
          onFilterChange={() => {}}
          sort="order"
          onSortChange={() => {}}
          followed={new Set()}
          onToggleFollow={() => {}}
          myTeamId={null}
          onlineCaptainIds={new Set()}
          onOpenProfile={() => {}}
          divisionGrid={{ tiers: [] }}
          ontology={ontology}
          clockColor="var(--aqt-fg)"
        />
      </NextIntlClientProvider>
    );
    const prefix = locale === "en" ? "Needs " : "Нужен ";
    return [...html.matchAll(/aria-label="([^"]*)"/g)].map((match) => match[1]).filter((name) => name.startsWith(prefix));
  }

  it("names each role's filter by its role", () => {
    expect(needNames(en, "en", OW_SHAPE, OW_METADATA)).toEqual([
      "Needs a tank: 2",
      "Needs damage: 2",
      "Needs a support: 2"
    ]);
    expect(needNames(ru, "ru", OW_SHAPE, OW_METADATA)).toEqual(["Нужен танк: 2", "Нужен дамаг: 2", "Нужен саппорт: 2"]);
  });

  it("falls back to the game's own role name for roles outside Overwatch's three", () => {
    const shape: RosterShape = { ...OW_SHAPE, dimension: "position", slots: { top: 1, jungle: 1, mid: 1, bot: 1, support: 1 } };
    const names = needNames(en, "en", shape, LOL_METADATA);

    expect(names).toHaveLength(5);
    expectDistinct(names);
    expect(names).toContain("Needs Jungle: 2");
  });
});

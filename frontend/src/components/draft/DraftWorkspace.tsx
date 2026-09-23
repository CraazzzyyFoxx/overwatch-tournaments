"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { canConfirmPick } from "@/lib/draft/logic";
import type { DraftGating } from "@/lib/draft/logic";
import {
  draftPoolView,
  DRAFT_MOBILE_VIEWS,
  type DraftMobileView,
  type DraftViewParams
} from "@/lib/draft/workspace-model";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import type {
  DraftBoard,
  DraftPickOptionsResponse,
  DraftPlayer,
  DraftRole
} from "@/types/draft.types";
import type { RealtimeConnectionState } from "@/types/realtime.types";
import type { DivisionGrid } from "@/types/workspace.types";
import type { DraftMutations } from "@/hooks/useDraftData";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";

import { DraftOrder } from "./DraftOrder";
import { PickCommandBar } from "./PickCommandBar";
import { PlayerPool } from "./PlayerPool";
import { PlayerProfileDialog } from "./PlayerProfileDialog";
import { TeamRosters } from "./TeamRosters";

interface DraftWorkspaceProps {
  board: DraftBoard;
  gating: DraftGating;
  options: DraftPickOptionsResponse | null;
  optionsLoading: boolean;
  onRetryOptions: () => void;
  connectionState: RealtimeConnectionState;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  mutations: DraftMutations;
  divisionGrid: DivisionGrid;
  onlineCaptainIds?: ReadonlySet<number>;
}

/**
 * ONE live draft room for every seat.
 *
 * Spectator, captain and admin used to be three different pages' worth of
 * layout; they are the same board read with different rights, so the same tree
 * renders for all three and `gating` decides which affordances exist. An admin
 * who is also a captain gets both.
 */
export function DraftWorkspace({
  board,
  gating,
  options,
  optionsLoading,
  onRetryOptions,
  connectionState,
  viewParams,
  onViewParamsChange,
  mutations,
  divisionGrid,
  onlineCaptainIds
}: Readonly<DraftWorkspaceProps>) {
  const t = useTranslations("draftRedesign");
  const [pendingSelection, setSelection] = useState<{ playerId: number; role: DraftRole } | null>(null);
  const [profilePlayer, setProfilePlayer] = useState<DraftPlayer | null>(null);
  // Persisted per session so a reload (or an accidental tab close) keeps the shortlist.
  const [shortlistIds, setShortlistIds] = useLocalStorageState<number[]>(
    `aqt.draft.shortlist.${board.session.id}`,
    []
  );
  const shortlist = useMemo(() => new Set(shortlistIds), [shortlistIds]);
  const pool = useMemo(
    () => draftPoolView(board.players, viewParams, shortlist),
    [board.players, viewParams, shortlist]
  );
  // A captain may line a pick up BEFORE their turn; the board can take that
  // player away in the meantime, and a selection pointing at somebody else's
  // roster is the one state the confirm button must never be built on. So the
  // stored pair is only LIVE while its player is still available — derived
  // here rather than cleared in an effect, which would render one frame with
  // the stale pick enabled.
  const storedPlayer =
    pendingSelection == null
      ? null
      : board.players.find((player) => player.id === pendingSelection.playerId) ?? null;
  const takenPlayer = storedPlayer != null && storedPlayer.status !== "available" ? storedPlayer : null;
  const selection = takenPlayer == null ? pendingSelection : null;
  const selectedPlayer = selection == null ? null : storedPlayer;
  const currentPick = board.current_pick;
  // Only claim a player is safe or blocked when the server's option list is
  // actually here. Without it every row would read as "no role keeps every
  // remaining roster feasible" — a verdict nobody computed.
  const safetyRequired = gating.isMyPick && options != null;
  const optionsUnavailable = gating.isMyPick && options == null && !optionsLoading;
  const confirmAllowed =
    gating.isMyPick &&
    currentPick != null &&
    canConfirmPick(connectionState, currentPick.version, options, selection);
  const pickBarVisible =
    currentPick != null || board.session.status === "live" || board.session.status === "paused";

  useEffect(() => {
    // Not when I am the one who just drafted them: that is a success, and it
    // already said so.
    if (takenPlayer && takenPlayer.drafted_by_team_id !== gating.myTeamId) {
      notify.info(t("selectionTaken", { player: takenPlayer.battle_tag ?? `#${takenPlayer.id}` }));
    }
  }, [takenPlayer, gating.myTeamId, t]);

  const selectRole = (player: DraftPlayer, role: DraftRole) => {
    setSelection(
      selection?.playerId === player.id && selection.role === role ? null : { playerId: player.id, role }
    );
  };
  const toggleShortlist = (playerId: number) => {
    setShortlistIds((current) =>
      current.includes(playerId) ? current.filter((id) => id !== playerId) : [...current, playerId]
    );
  };
  // Picking is a captain's right; reading a profile is everyone's.
  const canPick = gating.isCaptain || gating.isAdmin;

  const renderPool = (headingId: string) => (
    <PlayerPool
      players={pool.filtered}
      totalPlayers={
        viewParams.pool === "drafted"
          ? pool.drafted.length
          : viewParams.pool === "shortlist"
            ? pool.shortlist.length
            : pool.available.length
      }
      roleCounts={pool.roleCounts}
      poolCounts={{
        available: pool.available.length,
        shortlist: pool.shortlist.length,
        drafted: pool.drafted.length
      }}
      pool={viewParams.pool}
      selection={selection}
      shortlist={shortlist}
      role={viewParams.role}
      sort={viewParams.sort}
      query={viewParams.query}
      options={options}
      safetyRequired={safetyRequired}
      teams={board.teams}
      onSelect={canPick ? selectRole : undefined}
      onOpenProfile={setProfilePlayer}
      onToggleShortlist={canPick ? toggleShortlist : undefined}
      onFiltersChange={onViewParamsChange}
      onResetFilters={() => onViewParamsChange({ role: "all", sort: "rank", query: "" })}
      divisionGrid={divisionGrid}
      headingId={headingId}
    />
  );
  const rosters = (variant: "grid" | "column") => (
    <TeamRosters
      teams={board.teams}
      players={board.players}
      picks={board.picks}
      shape={board.session.roster_shape}
      myTeamId={gating.myTeamId}
      onClockTeamId={currentPick?.draft_team_id ?? null}
      variant={variant}
      divisionGrid={divisionGrid}
      onlineCaptainIds={onlineCaptainIds}
      onSlotFilter={
        gating.isCaptain ? (role) => onViewParamsChange({ role: role ?? "all" }) : undefined
      }
      activeSlotRole={viewParams.role === "all" ? null : viewParams.role}
    />
  );

  return (
    <div
      className={cn(
        "space-y-5",
        pickBarVisible && (gating.isAdmin ? "pb-48 sm:pb-44" : "pb-36 sm:pb-32")
      )}
    >
      {optionsLoading && gating.isMyPick && (
        // `block`: <output> is inline, so the left rule would be drawn per
        // line box instead of down the whole notice.
        <output className="block border-l-2 border-[color:var(--aqt-teal)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t("checkingSafeOptions")}
        </output>
      )}
      {optionsUnavailable && (
        <output className="flex flex-wrap items-center gap-2 border-l-2 border-[color:var(--aqt-live)] pl-3 text-sm text-[color:var(--aqt-fg-muted)]">
          {t("safeOptionsUnavailable")}
          <button
            type="button"
            onClick={onRetryOptions}
            className="min-h-11 text-[color:var(--aqt-teal)] underline outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
          >
            {t("retry")}
          </button>
        </output>
      )}
      {gating.isSpectator && (
        <p className="max-w-3xl text-sm text-[color:var(--aqt-fg-muted)]">
          {board.session.status === "completed" ? t("spectatorCompleted") : t("spectatorReadOnly")}
        </p>
      )}

      {/* Radix Tabs, not hand-rolled roles: it wires aria-controls, roving
          tabindex and arrow-key traversal that a plain button row lacks. */}
      <Tabs
        value={viewParams.view}
        onValueChange={(view) => onViewParamsChange({ view: view as DraftMobileView })}
        className="xl:hidden"
      >
        <TabsList
          className="flex h-auto w-full gap-1 rounded-xl bg-[color:var(--aqt-card-2)] p-1"
          aria-label={t("mobileViews")}
        >
          {DRAFT_MOBILE_VIEWS.map((view) => (
            <TabsTrigger
              key={view}
              value={view}
              className="min-h-11 flex-1 rounded-lg px-2 text-sm font-medium data-[state=active]:bg-[color:var(--aqt-card)] data-[state=active]:text-[color:var(--aqt-teal)] data-[state=active]:shadow-none"
            >
              {t(`mobileView.${MOBILE_VIEW_LABEL[view]}`)}
            </TabsTrigger>
          ))}
        </TabsList>
        <TabsContent value="pool" className="mt-5">
          {renderPool("player-pool-mobile-heading")}
        </TabsContent>
        <TabsContent value="team" className="mt-5">
          {rosters("grid")}
        </TabsContent>
        <TabsContent value="order" className="mt-5">
          <DraftOrder
            picks={board.picks}
            teams={board.teams}
            players={board.players}
            compact
            divisionGrid={divisionGrid}
            headingId="draft-order-mobile-heading"
          />
        </TabsContent>
      </Tabs>

      <div className="hidden gap-4 xl:grid xl:grid-cols-[248px_minmax(0,1fr)_378px]">
        <aside className="sticky top-4 self-start">
          <DraftOrder
            picks={board.picks}
            teams={board.teams}
            players={board.players}
            divisionGrid={divisionGrid}
            headingId="draft-order-desktop-heading"
          />
        </aside>
        {/* Not <main>: the route already exposes the page-level main landmark. */}
        <div className="min-w-0">{renderPool("player-pool-desktop-heading")}</div>
        <aside className="sticky top-4 max-h-[calc(100svh-2rem)] self-start overflow-y-auto">
          {rosters("column")}
        </aside>
      </div>

      {pickBarVisible && (
        <PickCommandBar
          board={board}
          gating={gating}
          selection={selectedPlayer && selection ? { player: selectedPlayer, role: selection.role } : null}
          canConfirm={confirmAllowed}
          connectionState={connectionState}
          mutations={mutations}
          onClearSelection={() => setSelection(null)}
          divisionGrid={divisionGrid}
          onlineCaptainIds={onlineCaptainIds}
        />
      )}

      <PlayerProfileDialog
        player={profilePlayer}
        open={profilePlayer != null}
        onOpenChange={(open) => !open && setProfilePlayer(null)}
        board={board}
        divisionGrid={divisionGrid}
      />
    </div>
  );
}

/** The team tab shows EVERY roster, so it is named for what it holds. */
const MOBILE_VIEW_LABEL = {
  pool: "players",
  team: "rosters",
  order: "order"
} as const satisfies Record<DraftMobileView, string>;


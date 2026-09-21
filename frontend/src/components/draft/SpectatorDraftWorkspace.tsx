"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  DRAFT_MOBILE_VIEWS,
  draftPoolView,
  type DraftMobileView,
  type DraftViewParams
} from "@/lib/draft-workspace-model";
import { cn } from "@/lib/utils";
import type { DraftBoard } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { CurrentPick } from "./CurrentPick";
import { DraftOrder } from "./DraftOrder";
import { PlayerPool } from "./PlayerPool";
import { TeamRosters } from "./TeamRosters";

interface SpectatorDraftWorkspaceProps {
  board: DraftBoard;
  divisionGrid: DivisionGrid;
  viewParams: DraftViewParams;
  onViewParamsChange: (patch: Partial<DraftViewParams>) => void;
  /** Online captain auth ids, for the TeamRosters captain presence dots. */
  onlineCaptainIds?: Set<number>;
}

/** A spectator has no team and reads no "pool": name the tabs for a viewer. */
const SPECTATOR_VIEW_LABEL = {
  pool: "players",
  team: "rosters",
  order: "order"
} as const satisfies Record<DraftMobileView, string>;

export function SpectatorDraftWorkspace({
  board,
  divisionGrid,
  viewParams,
  onViewParamsChange,
  onlineCaptainIds
}: Readonly<SpectatorDraftWorkspaceProps>) {
  const t = useTranslations("draftRedesign");
  const pool = useMemo(() => draftPoolView(board.players, viewParams), [board.players, viewParams]);
  const poolExhausted = pool.available.length === 0;
  const showCurrentPick =
    board.current_pick != null ||
    board.session.status === "live" ||
    board.session.status === "paused";

  // Same PlayerPool the captain drives, minus `onSelect`/`onToggleShortlist`:
  // without them it renders as a plain, readable list. Already-picked players
  // are deliberately absent — they are in the rosters beside it.
  const renderPool = (headingId: string) => (
    <PlayerPool
      players={pool.filtered}
      totalPlayers={pool.available.length}
      roleCounts={pool.roleCounts}
      role={viewParams.role}
      sort={viewParams.sort}
      query={viewParams.query}
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
      onClockTeamId={board.current_pick?.draft_team_id ?? null}
      variant={variant}
      divisionGrid={divisionGrid}
      onlineCaptainIds={onlineCaptainIds}
    />
  );

  return (
    <div className="space-y-5">
      {showCurrentPick ? <CurrentPick board={board} /> : null}
      <p className="max-w-3xl text-sm text-[color:var(--aqt-fg-muted)]">
        {board.session.status === "completed" ? t("spectatorCompleted") : t("spectatorReadOnly")}
      </p>

      {/* Radix Tabs, not hand-rolled roles: it wires aria-controls, roving
          tabindex and arrow-key traversal. Without them the order sat below
          every roster — roughly 6000px down on a 14-team draft. */}
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
              {t(`mobileView.${SPECTATOR_VIEW_LABEL[view]}`)}
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

      {/* Live: the captain room's three-column geometry, so the page does not
          rearrange itself when a captain signs in. Finished: the pool column
          is empty, so the rosters — the only thing left to read — take it. */}
      <div
        className={cn(
          "hidden gap-4 xl:grid",
          poolExhausted ? "xl:grid-cols-[248px_minmax(0,1fr)]" : "xl:grid-cols-[248px_minmax(0,1fr)_378px]"
        )}
      >
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
        {poolExhausted ? (
          <div className="min-w-0">{rosters("grid")}</div>
        ) : (
          <>
            <div className="min-w-0">{renderPool("player-pool-desktop-heading")}</div>
            <aside className="sticky top-4 max-h-[calc(100svh-2rem)] self-start overflow-y-auto">
              {rosters("column")}
            </aside>
          </>
        )}
      </div>
    </div>
  );
}

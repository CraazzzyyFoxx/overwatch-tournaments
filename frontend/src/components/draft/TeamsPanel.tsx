"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  filterSortTeams,
  remainingPicks,
  roundDirection,
  roundNumbers,
  type RoundDirection,
  type TeamFilter,
  type TeamSort,
  type TeamView
} from "@/lib/draft/room-model";
import { DRAFT_TEAMS_TABS, type DraftTeamsTab } from "@/lib/draft/workspace-model";
import type { DraftBoard, DraftRole } from "@/types/draft.types";
import type { DivisionGrid } from "@/types/workspace.types";

import { DraftOrderGrid } from "./DraftOrderGrid";
import { DraftQueue } from "./DraftQueue";
import { TeamRosters } from "./TeamRosters";

interface TeamsPanelProps {
  board: DraftBoard;
  teamViews: ReadonlyMap<number, TeamView>;
  tab: DraftTeamsTab;
  onTabChange: (tab: DraftTeamsTab) => void;
  filter: TeamFilter;
  onFilterChange: (filter: TeamFilter) => void;
  sort: TeamSort;
  onSortChange: (sort: TeamSort) => void;
  followed: ReadonlySet<number>;
  onToggleFollow: (teamId: number) => void;
  myTeamId: number | null;
  onlineCaptainIds: ReadonlySet<number>;
  onOpenProfile: (playerId: number) => void;
  /** Captain only: an open ROLE slot of MY team filters the pool to that role. */
  onSlotFilter?: (role: DraftRole) => void;
  divisionGrid: DivisionGrid;
  headingId: string;
}

/** How the whole order reads, from each round's actual direction — never from the format name. */
export type OrderKind = "linear" | "snake" | "custom";

function orderKind(directions: readonly RoundDirection[]): OrderKind {
  if (directions.every((direction) => direction === "forward")) return "linear";
  const alternates = directions.every(
    (direction, index) => direction !== "custom" && (index === 0 || direction !== directions[index - 1])
  );
  return alternates ? "snake" : "custom";
}

/** The on-clock accent every surface of the room shares: paused amber, overtime rose, my turn teal. */
function clockAccent(board: DraftBoard, myTeamId: number | null): string {
  const pick = board.current_pick;
  if (board.session.status === "paused") return "var(--aqt-amber)";
  if (pick?.overtime_started_at != null) return "var(--aqt-rose)";
  if (pick != null && pick.draft_team_id === myTeamId) return "var(--aqt-teal)";
  return "var(--aqt-fg)";
}

function isTeamsTab(value: string): value is DraftTeamsTab {
  return (DRAFT_TEAMS_TABS as readonly string[]).includes(value);
}

export function TeamsPanel({
  board,
  teamViews,
  tab,
  onTabChange,
  filter,
  onFilterChange,
  sort,
  onSortChange,
  followed,
  onToggleFollow,
  myTeamId,
  onlineCaptainIds,
  onOpenProfile,
  onSlotFilter,
  divisionGrid,
  headingId
}: Readonly<TeamsPanelProps>) {
  const t = useTranslations("draftRedesign");
  const rounds = useMemo(() => roundNumbers(board), [board]);
  const directions = useMemo(() => rounds.map((round) => roundDirection(board, round)), [board, rounds]);
  const kind = orderKind(directions);
  const remaining = useMemo(() => remainingPicks(board), [board]);
  const teams = useMemo(
    () => filterSortTeams(board, teamViews, { filter, sort, followed, myTeamId }),
    [board, teamViews, filter, sort, followed, myTeamId]
  );
  const clockColor = clockAccent(board, myTeamId);
  const totalPicks = board.picks.length;

  const caption =
    tab === "order"
      ? t("teams.caption.order", { kind, count: totalPicks })
      : tab === "queue"
        ? t("teams.caption.queue", { pick: board.current_pick?.overall_no ?? totalPicks, total: totalPicks })
        : teams.length === teamViews.size
          ? t("teams.caption.rosters", { count: teamViews.size })
          : t("teams.caption.rostersFiltered", { shown: teams.length, total: teamViews.size });

  const tabs: { value: DraftTeamsTab; label: string; count: string }[] = [
    { value: "rosters", label: t("teams.tabs.rosters"), count: String(teamViews.size) },
    { value: "queue", label: t("teams.tabs.queue"), count: String(remaining.length) },
    { value: "order", label: t("teams.tabs.order"), count: t("teams.tabs.orderCount", { count: rounds.length }) }
  ];

  return (
    <section
      aria-labelledby={headingId}
      className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] shadow-[0_1px_2px_rgb(0_0_0/0.25)] xl:h-full"
    >
      <Tabs
        value={tab}
        onValueChange={(value) => {
          if (isTeamsTab(value)) onTabChange(value);
        }}
        className="flex min-h-0 flex-1 flex-col"
      >
        <div className="flex flex-col gap-2 px-4 pb-3 pt-3.5">
          <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1">
            <h2 id={headingId} className="font-onest text-base font-semibold leading-[1.3]">
              {t("teams.title")}
            </h2>
            <span className="ml-auto whitespace-nowrap text-[13px] text-[color:var(--aqt-fg-dim)]">{caption}</span>
          </div>
          <TabsList aria-label={t("teams.tabsLabel")}>
            {tabs.map((entry) => (
              <TabsTrigger key={entry.value} value={entry.value} badge={entry.count} className="max-sm:h-11">
                {entry.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </div>

        <TabsContent value="rosters" className="mt-0 flex min-h-0 flex-1 flex-col focus-visible:ring-inset">
          <TeamRosters
            board={board}
            teamViews={teamViews}
            teams={teams}
            filter={filter}
            onFilterChange={onFilterChange}
            sort={sort}
            onSortChange={onSortChange}
            followed={followed}
            onToggleFollow={onToggleFollow}
            myTeamId={myTeamId}
            onlineCaptainIds={onlineCaptainIds}
            onOpenProfile={onOpenProfile}
            onSlotFilter={onSlotFilter}
            divisionGrid={divisionGrid}
            clockColor={clockColor}
          />
        </TabsContent>
        <TabsContent value="queue" className="mt-0 flex min-h-0 flex-1 flex-col focus-visible:ring-inset">
          <DraftQueue
            board={board}
            teamViews={teamViews}
            remaining={remaining}
            myTeamId={myTeamId}
            clockColor={clockColor}
          />
        </TabsContent>
        <TabsContent value="order" className="mt-0 flex min-h-0 flex-1 flex-col focus-visible:ring-inset">
          <DraftOrderGrid
            board={board}
            rounds={rounds}
            directions={directions}
            kind={kind}
            myTeamId={myTeamId}
            followed={followed}
            clockColor={clockColor}
          />
        </TabsContent>
      </Tabs>
    </section>
  );
}

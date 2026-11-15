"use client";

import { useTranslations } from "next-intl";

import RankHistory from "@/components/RankHistory";
import { PersonPastRanks } from "@/components/admin/people/PersonPastRanks";
import { PersonRankCollection } from "@/components/admin/people/PersonRankCollection";
import { PersonRankMatrix } from "@/components/admin/people/PersonRankMatrix";
import { SettingGroup } from "@/components/kit/SettingRow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameScope } from "@/hooks/useGameScope";
import { cn } from "@/lib/utils";
import { useWorkspaceStore } from "@/stores/workspace.store";

/**
 * Current ranks left, the collection right beside them from `xl`; one column below. The matrix card is capped, not
 * stretched over the page: a three-role table in a 1fr card pushed the accounts a screen away from it. Not
 * `max-content` either: a card's body is a size container, so it has no width of its own to give the track.
 */
const TOP_GRID = "xl:grid-cols-[minmax(0,56rem)_minmax(0,26rem)]";

/**
 * The person hub's Ranks tab: one game at a time, picked by the one game switcher at its top (`?discipline=`; the hub
 * is game-neutral, so platform rules — the first game unless the URL names one). Every card below reads that game:
 * current ranks, collection, the history chart and past ratings.
 *
 * `canReadRanks` is `team.update`, the grant the workspace ranks endpoint checks; without it the two cards read from
 * there are absent, and the collection and the history stay.
 */
export function PersonRanksTab({ personId, canReadRanks }: Readonly<{ personId: number; canReadRanks: boolean }>) {
  const t = useTranslations("adminPeople.rank");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const scope = useGameScope({ pageClass: "platform", axis: workspaceId ?? "all" });
  const game = scope.game;
  const withRanks = canReadRanks && workspaceId != null;

  if (scope.isError) return <PageStateCard state="error" onAction={scope.refetch} />;
  if (scope.resolution === null) {
    return (
      <div className="space-y-4" aria-hidden>
        <Skeleton className="h-9 w-72" />
        <div className={cn("grid items-start gap-4", withRanks && TOP_GRID)}>
          {withRanks ? <Skeleton className="h-64 rounded-xl" /> : null}
          <Skeleton className="h-40 rounded-xl" />
        </div>
        <Skeleton className="h-72 rounded-xl" />
      </div>
    );
  }
  // An invalid or empty pick: the control alone names it, with its way out.
  if (game === null) return <GameScopeControl scope={scope} variant="single" />;

  const descriptor = scope.games?.find((entry) => entry.code === game);
  return (
    <div className="space-y-4">
      <GameScopeControl scope={scope} variant="single" />
      {/* Keyed by game: nothing of the previous game's reads or a pending re-fetch lingers. */}
      <div key={game} className="space-y-4">
        <div className={cn("grid items-start gap-4", withRanks && TOP_GRID)}>
          {withRanks ? (
            <PersonRankMatrix workspaceId={workspaceId} personId={personId} game={game} axis={scope.axis} />
          ) : null}
          <PersonRankCollection
            personId={personId}
            game={game}
            supported={descriptor?.capabilities.native_rank_collection === true}
          />
        </div>
        <SettingGroup id="history" title={t("history")}>
          {/* An explicit game: the chart draws no game tabs of its own. The card is its frame. */}
          <RankHistory userId={personId} discipline={game} framed={false} />
        </SettingGroup>
        {withRanks ? (
          <PersonPastRanks workspaceId={workspaceId} personId={personId} game={game} axis={scope.axis} />
        ) : null}
      </div>
    </div>
  );
}

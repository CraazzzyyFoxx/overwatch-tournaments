"use client";

import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameBoundParams } from "@/components/workspace/scope-pill-store";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useGameScope } from "@/hooks/useGameScope";
import { isDivisionGridRequired } from "@/lib/api/error";
import type { GameScopeInit } from "@/lib/site/discipline-scope";
import type { StatsScope } from "@/lib/site/stats-scope";
import { UsersMissingGrid } from "@/app/(site)/users/components/shared/UsersMissingGrid";

import { useUsersIndexParams } from "./useUsersIndexParams";
import { useUsersIndexData } from "./useUsersIndexData";
import { UsersIndexHero } from "./UsersIndexHero";
import { UsersIndexFilters } from "./UsersIndexFilters";
import { UsersTableView } from "./UsersTableView";
import { UsersCatalogView } from "./UsersCatalogView";
import { UsersCompareBar, useCompareSelection } from "./UsersCompareBar";

/** URL filters that only mean something inside one game; a scope pick from a row drops them. */
const GAME_BOUND_PARAMS = ["role", "div"];

/**
 * The player index (spec §6.7, a multi page). Under a game it is that game's index; under "all games" one row per
 * player spans every game, each row marks the games played (a mark narrows the scope), and the role chips, division
 * facet, role divisions and top characters step aside. Both views share one set of URL-backed filters; only the one
 * on screen fetches its own list, and the compare selection survives a switch between them.
 *
 * `scope` is resolved on the server (the cross-workspace mode does not exist on a tenant host).
 */
const UsersClient = ({ scope, initial }: Readonly<{ scope: StatsScope; initial: GameScopeInit }>) => {
  const gameScope = useGameScope({ pageClass: "multi", initial });
  const kind = gameScope.resolution?.game.kind;
  // `null` under "all games" (and while unresolved): every read then spans the scope's games.
  const discipline = gameScope.game;
  const resolved = kind === "game" || kind === "all";
  // The game's roles name the role chips and its native ladder is the all-communities division facet.
  const metadata = useDisciplineMetadata(gameScope.axis, discipline).data ?? null;
  const controls = useUsersIndexParams(scope, discipline, metadata);
  const data = useUsersIndexData(controls.params, discipline, metadata, resolved);
  const compare = useCompareSelection();
  const { view } = controls.params;
  const selectGame = (code: string) => gameScope.selectScope(code, { dropParams: GAME_BOUND_PARAMS });
  // R5: the pill's game pick drops these too.
  useGameBoundParams(GAME_BOUND_PARAMS);
  // The game has no grid on this axis: every list read is refused the same way, so the notice stands in for the view.
  const gridMissing = isDivisionGridRequired((view === "catalog" ? data.catalogQuery : data.overviewQuery).error);

  if (kind === "invalid" || kind === "empty") {
    return <GameScopeControl scope={gameScope} variant="multi" dropParams={GAME_BOUND_PARAMS} headingLevel={1} />;
  }

  return (
    <div className="space-y-4">
      <UsersIndexHero stats={data.statsQuery.data} />
      <UsersIndexFilters
        controls={controls}
        stats={data.statsQuery.data}
        ontology={data.ontology}
        allGames={kind === "all"}
        // `null` means "we could not load it", which is not a count of zero and
        // not a load that is still running.
        foundCount={
          view === "catalog"
            ? data.catalogQuery.isError
              ? null
              : data.catalogQuery.data?.total
            : data.overviewQuery.isError
              ? null
              : data.overviewQuery.data?.total
        }
      />

      {gridMissing && discipline ? (
        <UsersMissingGrid
          discipline={discipline}
          gameName={gameScope.games?.find((entry) => entry.code === discipline)?.name ?? discipline}
          axis={data.workspaceId}
        />
      ) : view === "catalog" ? (
        <UsersCatalogView controls={controls} data={data} compare={compare} onSelectGame={selectGame} />
      ) : (
        <UsersTableView controls={controls} data={data} compare={compare} onSelectGame={selectGame} />
      )}

      <UsersCompareBar compare={compare} />
    </div>
  );
};

export default UsersClient;

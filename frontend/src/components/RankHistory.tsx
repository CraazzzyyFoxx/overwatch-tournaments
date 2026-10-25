"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Link2Off, Radar } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { ChartEmptyState, RankHistorySkeleton } from "@/components/RankHistoryState";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { DisciplineWidget } from "@/disciplines/DisciplineWidget";
import { loadRankUI } from "@/disciplines/registry/rank";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
import { useNativeRankCollector } from "@/hooks/useNativeRankCollector";
import { userQueryKeys } from "@/lib/users/query-keys";
import { cn } from "@/lib/utils";
import userService from "@/services/user.service";

/**
 * The player is identified by exactly one of these. `userId` is the cheap path;
 * `battleTag` costs a lookup, so callers that already hold the id pass that
 * instead. The lookup is the profile-slug read: it finds canonical names and
 * `#` handles, never a Steam account id (Deadlock). Either may be nullish — that
 * renders the "no linked profile" state.
 */
type RankHistoryTarget =
  | { userId: number | null | undefined; battleTag?: never }
  | { battleTag: string | null | undefined; userId?: never };

type RankHistoryProps = RankHistoryTarget & {
  /**
   * The owning game (tournament, mix, draft, registration…). Without one the single-page rules pick it, with local
   * game tabs under "all games" — on a game-neutral page (the person hub) the platform rules, with tabs under any
   * scope (R23). Either way the game is resolved first and only then checked for rank collection:
   * a game that does not collect ranks gets the unsupported state, never another game's history.
   */
  discipline?: string | null;
  /** When set, the chart is wrapped in a titled card; otherwise it renders bare. */
  title?: string;
  /** `false` inside a card that already frames the chart: no tiles, chart box or state box of its own. */
  framed?: boolean;
  className?: string;
};

/**
 * Rank history for one player: resolves the player and the game, gates on the discipline's native-rank
 * collection capability and hands the drawing to that game's `rankHistory` module slot. Used on the player
 * profile, the admin rank console, the registration review and the balancer player sheet.
 */
export default function RankHistory({
  userId,
  battleTag,
  discipline,
  title,
  framed = true,
  className
}: Readonly<RankHistoryProps>) {
  const t = useTranslations();
  const axis = useCurrentWorkspaceId() ?? "all";
  const collector = useNativeRankCollector(axis, discipline);

  const resolve = useQuery({
    queryKey: userQueryKeys.rankResolve(battleTag),
    queryFn: async () => {
      if (!battleTag) return null;
      const user = await userService.getUserByName(battleTag).catch(() => null);
      return user?.id ?? null;
    },
    staleTime: 5 * 60_000,
    enabled: Boolean(battleTag)
  });
  const resolvedUserId = battleTag === undefined ? (userId ?? null) : (resolve.data ?? null);

  // `title` owns the card chrome, so the caller's className lands on the Card
  // there and on the bare content otherwise.
  const contentClassName = title == null ? className : undefined;
  const descriptor = collector.descriptor;

  let content: ReactNode;
  if (resolve.isLoading || (collector.scope.resolution === null && !collector.scope.isError)) {
    content = <RankHistorySkeleton className={contentClassName} framed={framed} />;
  } else if (resolvedUserId == null) {
    content = (
      <ChartEmptyState
        className={contentClassName}
        icon={Link2Off}
        title={t("rankHistory.noProfileTitle")}
        body={t("rankHistory.noProfileBody")}
        framed={framed}
      />
    );
  } else if (collector.scope.isError) {
    content = (
      <ChartEmptyState
        className={contentClassName}
        icon={AlertCircle}
        tone="error"
        title={t("rankHistory.errorTitle")}
        body={t("rankHistory.errorBody")}
        framed={framed}
      />
    );
  } else {
    const kind = collector.scope.resolution?.game.kind;
    content = (
      <div className={cn("space-y-3", contentClassName)}>
        {/* An invalid/empty resolution named with its way out (never read as "this game collects no ranks"), or —
            ownerless, when the resolution asks for them — the local game tabs, whether or not the picked game collects
            ranks. */}
        <GameScopeControl scope={collector.scope} variant="single" />
        {kind === "invalid" || kind === "empty" ? null : descriptor && collector.supported ? (
          <DisciplineWidget
            discipline={descriptor.code}
            load={loadRankUI}
            slot="rankHistory"
            capabilities={descriptor.capabilities}
            requires="native_rank_collection"
            props={{ userId: resolvedUserId, axis, discipline: descriptor.code, framed }}
            fallback={null}
          />
        ) : (
          <ChartEmptyState
            icon={Radar}
            title={t("rankHistory.unsupportedTitle")}
            body={t("rankHistory.unsupportedBody")}
            framed={framed}
          />
        )}
      </div>
    );
  }

  if (title == null) return content;

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}

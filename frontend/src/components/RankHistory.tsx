"use client";

import { useMemo, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Link2Off } from "lucide-react";
import { useTranslations } from "next-intl";

import RankHistoryChart, {
  ChartEmptyState,
  RankHistorySkeleton
} from "@/components/RankHistoryChart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  BACKEND_GRANULARITY,
  getDefaultDateFrom,
  useRankHistoryGranularity,
  useUserRankHistory
} from "@/hooks/useRankHistory";
import userService from "@/services/user.service";
import { userQueryKeys } from "@/lib/users/query-keys";

/**
 * The player is identified by exactly one of these. `userId` is the cheap path;
 * `battleTag` costs a lookup, so callers that already hold the id pass that
 * instead. Either may be nullish — that renders the "no linked profile" state.
 */
type RankHistoryTarget =
  | { userId: number | null | undefined; battleTag?: never }
  | { battleTag: string | null | undefined; userId?: never };

type RankHistoryProps = RankHistoryTarget & {
  /** When set, the chart is wrapped in a titled card; otherwise it renders bare. */
  title?: string;
  className?: string;
};

/**
 * OverFast rank history for one player, across all their battle.net accounts.
 * Used on the player profile, the admin rank console, the registration review
 * and the balancer player sheet.
 */
export default function RankHistory({ userId, battleTag, title, className }: RankHistoryProps) {
  const t = useTranslations();
  const [granularity, setGranularity] = useRankHistoryGranularity();
  const dateFrom = useMemo(() => getDefaultDateFrom(granularity), [granularity]);

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

  const resolvedUserId = battleTag === undefined ? userId ?? null : resolve.data ?? null;
  const history = useUserRankHistory(resolvedUserId ?? NaN, {
    granularity: BACKEND_GRANULARITY[granularity],
    dateFrom
  });

  // `title` owns the card chrome, so the caller's className lands on the Card
  // there and on the bare content otherwise.
  const contentClassName = title == null ? className : undefined;

  let content: ReactNode;
  if (resolve.isLoading || (resolvedUserId != null && history.isLoading)) {
    content = <RankHistorySkeleton className={contentClassName} />;
  } else if (resolvedUserId == null) {
    content = (
      <ChartEmptyState
        className={contentClassName}
        icon={Link2Off}
        title={t("rankHistory.noProfileTitle")}
        body={t("rankHistory.noProfileBody")}
      />
    );
  } else if (history.isError) {
    content = (
      <ChartEmptyState
        className={contentClassName}
        icon={AlertCircle}
        tone="error"
        title={t("rankHistory.errorTitle")}
        body={t("rankHistory.errorBody")}
      />
    );
  } else {
    content = (
      <RankHistoryChart
        className={contentClassName}
        series={history.data?.series ?? []}
        granularity={granularity}
        onGranularityChange={setGranularity}
      />
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

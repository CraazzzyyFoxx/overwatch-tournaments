"use client";

import { useMemo } from "react";
import { AlertCircle } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import RankHistoryChart, { RankHistorySkeleton } from "@/components/RankHistoryChart";
import { useUserRankHistory } from "@/hooks/useRankHistory";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useTranslations } from "next-intl";

type Granularity = "date" | "hour" | "raw";

function getDefaultDateFrom(g: Granularity): string {
  const days = g === "date" ? 14 : 3;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

interface UserRankHistoryProps {
  userId: number;
  title?: string;
  className?: string;
}

/**
 * Drop-in card showing a user's OverFast rank history across all their
 * battle.net accounts. Used on the player profile, the registration review and
 * the balancer player sheet.
 */
export default function UserRankHistory({ userId, title, className }: UserRankHistoryProps) {
  const t = useTranslations();
  const [granularity, setGranularity] = useLocalStorageState<Granularity>("rank-history-granularity", "date");
  const dateFrom = useMemo(() => getDefaultDateFrom(granularity), [granularity]);
  const backendGranularity = granularity === "date" ? "daily" : granularity === "hour" ? "hourly" : "raw";
  const { data, isLoading, isError } = useUserRankHistory(userId, {
    granularity: backendGranularity,
    dateFrom,
  });
  const series = data?.series ?? [];

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title ?? t("rankHistory.title")}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <RankHistorySkeleton />
        ) : isError ? (
          <div className="flex flex-col items-center justify-center text-center p-6 rounded-xl border border-rose-500/10 bg-rose-500/[0.02]">
            <AlertCircle className="h-5 w-5 text-rose-400/50 mb-2" />
            <h4 className="text-xs font-semibold text-rose-300/70 mb-1">
              {t("rankHistory.errorTitle")}
            </h4>
            <p className="text-[11px] text-rose-400/40 max-w-xs leading-normal">
              {t("rankHistory.errorBody")}
            </p>
          </div>
        ) : (
          <RankHistoryChart series={series} granularity={granularity} onGranularityChange={setGranularity} />
        )}
      </CardContent>
    </Card>
  );
}

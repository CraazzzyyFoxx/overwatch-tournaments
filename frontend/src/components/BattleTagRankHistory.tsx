"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link2Off, AlertCircle } from "lucide-react";

import RankHistoryChart, { RankHistorySkeleton } from "@/components/RankHistoryChart";
import { useUserRankHistory } from "@/hooks/useRankHistory";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import userService from "@/services/user.service";
import { useTranslations } from "next-intl";

type Granularity = "date" | "hour" | "raw";

function getDefaultDateFrom(g: Granularity): string {
  const days = g === "date" ? 14 : 3;
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString();
}

interface BattleTagRankHistoryProps {
  /** Domain user id, when already known (preferred — avoids a lookup). */
  userId?: number | null;
  /** Battle tag used to resolve the user when `userId` is not provided. */
  battleTag?: string | null;
  className?: string;
}

/**
 * Renders OverFast rank history for a player, resolving the domain user from a
 * battle tag when an explicit `userId` is not available. Used by the balancer
 * player sheet and the registration review, where players are keyed by battle
 * tag rather than user id.
 */
export default function BattleTagRankHistory({
  userId = null,
  battleTag = null,
  className
}: BattleTagRankHistoryProps) {
  const t = useTranslations();
  const resolve = useQuery({
    queryKey: ["rank-user-resolve", userId, battleTag],
    queryFn: async () => {
      if (userId != null) return userId;
      if (!battleTag) return null;
      const user = await userService.getUserByName(battleTag).catch(() => null);
      return user?.id ?? null;
    },
    staleTime: 5 * 60_000,
    enabled: userId != null || Boolean(battleTag)
  });

  const [granularity, setGranularity] = useLocalStorageState<Granularity>("rank-history-granularity", "date");
  const dateFrom = useMemo(() => getDefaultDateFrom(granularity), [granularity]);
  const backendGranularity = granularity === "date" ? "daily" : granularity === "hour" ? "hourly" : "raw";

  const resolvedUserId = resolve.data ?? null;
  const history = useUserRankHistory(typeof resolvedUserId === "number" ? resolvedUserId : NaN, {
    granularity: backendGranularity,
    dateFrom,
  });

  if (resolve.isLoading || (resolvedUserId != null && history.isLoading)) {
    return <RankHistorySkeleton className={className} />;
  }
  if (resolvedUserId == null) {
    return (
      <div className={`flex flex-col items-center justify-center text-center p-6 rounded-xl border border-white/[0.06] bg-zinc-950/20 ${className || ""}`}>
        <Link2Off className="h-5 w-5 text-white/30 mb-2" />
        <h4 className="text-xs font-semibold text-white/70 mb-1">
          {t("rankHistory.noProfileTitle")}
        </h4>
        <p className="text-[11px] text-white/45 max-w-xs leading-normal">
          {t("rankHistory.noProfileBody")}
        </p>
      </div>
    );
  }
  if (history.isError) {
    return (
      <div className={`flex flex-col items-center justify-center text-center p-6 rounded-xl border border-rose-500/10 bg-rose-500/[0.02] ${className || ""}`}>
        <AlertCircle className="h-5 w-5 text-rose-400/50 mb-2" />
        <h4 className="text-xs font-semibold text-rose-300/70 mb-1">
          {t("rankHistory.errorTitle")}
        </h4>
        <p className="text-[11px] text-rose-400/40 max-w-xs leading-normal">
          {t("rankHistory.errorBody")}
        </p>
      </div>
    );
  }

  return <RankHistoryChart series={history.data?.series ?? []} className={className} granularity={granularity} onGranularityChange={setGranularity} />;
}

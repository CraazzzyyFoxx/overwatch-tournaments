"use client";

import { useQuery } from "@tanstack/react-query";
import { Link2Off, AlertCircle } from "lucide-react";

import RankHistoryChart, { RankHistorySkeleton } from "@/components/RankHistoryChart";
import { useUserRankHistory } from "@/hooks/useRankHistory";
import userService from "@/services/user.service";
import { useTranslation } from "@/i18n/LanguageContext";

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
  const { locale } = useTranslation();
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

  const resolvedUserId = resolve.data ?? null;
  const history = useUserRankHistory(typeof resolvedUserId === "number" ? resolvedUserId : NaN);

  if (resolve.isLoading || (resolvedUserId != null && history.isLoading)) {
    return <RankHistorySkeleton className={className} />;
  }
  if (resolvedUserId == null) {
    const isRu = locale.startsWith("ru");
    return (
      <div className={`flex flex-col items-center justify-center text-center p-6 rounded-xl border border-white/[0.06] bg-zinc-950/20 ${className || ""}`}>
        <Link2Off className="h-5 w-5 text-white/30 mb-2" />
        <h4 className="text-xs font-semibold text-white/70 mb-1">
          {isRu ? "Нет привязанного профиля" : "No linked player profile"}
        </h4>
        <p className="text-[11px] text-white/45 max-w-xs leading-normal">
          {isRu
            ? "История рангов недоступна, так как этот BattleTag не связан с зарегистрированным аккаунтом на сайте."
            : "Rank history is unavailable because this BattleTag is not linked to a registered site account."}
        </p>
      </div>
    );
  }
  if (history.isError) {
    const isRu = locale.startsWith("ru");
    return (
      <div className={`flex flex-col items-center justify-center text-center p-6 rounded-xl border border-rose-500/10 bg-rose-500/[0.02] ${className || ""}`}>
        <AlertCircle className="h-5 w-5 text-rose-400/50 mb-2" />
        <h4 className="text-xs font-semibold text-rose-300/70 mb-1">
          {isRu ? "Ошибка загрузки" : "Failed to load"}
        </h4>
        <p className="text-[11px] text-rose-400/40 max-w-xs leading-normal">
          {isRu
            ? "Не удалось загрузить историю рангов. Пожалуйста, попробуйте позже."
            : "Failed to load rank history. Please try again later."}
        </p>
      </div>
    );
  }

  return <RankHistoryChart series={history.data?.series ?? []} className={className} />;
}

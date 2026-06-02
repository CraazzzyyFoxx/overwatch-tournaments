"use client";

import { AlertCircle } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import RankHistoryChart, { RankHistorySkeleton } from "@/components/RankHistoryChart";
import { useUserRankHistory } from "@/hooks/useRankHistory";
import { useTranslation } from "@/i18n/LanguageContext";

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
export default function UserRankHistory({ userId, title = "Rank history", className }: UserRankHistoryProps) {
  const { locale } = useTranslation();
  const { data, isLoading, isError } = useUserRankHistory(userId);
  const series = data?.series ?? [];

  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <RankHistorySkeleton />
        ) : isError ? (
          <div className="flex flex-col items-center justify-center text-center p-6 rounded-xl border border-rose-500/10 bg-rose-500/[0.02]">
            <AlertCircle className="h-5 w-5 text-rose-400/50 mb-2" />
            <h4 className="text-xs font-semibold text-rose-300/70 mb-1">
              {locale.startsWith("ru") ? "Ошибка загрузки" : "Failed to load"}
            </h4>
            <p className="text-[11px] text-rose-400/40 max-w-xs leading-normal">
              {locale.startsWith("ru")
                ? "Не удалось загрузить историю рангов. Пожалуйста, попробуйте позже."
                : "Failed to load rank history. Please try again later."}
            </p>
          </div>
        ) : (
          <RankHistoryChart series={series} />
        )}
      </CardContent>
    </Card>
  );
}

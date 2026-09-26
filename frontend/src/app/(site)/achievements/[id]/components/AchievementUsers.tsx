"use client";

import { useState } from "react";
import Link from "next/link";
import { Swords, Trophy, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Achievement } from "@/types/achievement.types";
import achievementsService from "@/services/achievements.service";
import PlayerName from "@/components/PlayerName";
import TeamName from "@/components/TeamName";
import { DataPagination } from "@/components/ui/data-pagination";
import { Skeleton } from "@/components/ui/skeleton";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";

const PER_PAGE = 30;

const AchievementUsers = ({ achievement }: { achievement: Achievement }) => {
  const t = useTranslations();
  const [page, setPage] = useState(1);

  const { data, isLoading, isError } = useQuery({
    queryKey: achievementQueryKeys.users(achievement.id, page),
    queryFn: () => achievementsService.getUsers(achievement.id, page, PER_PAGE),
    placeholderData: keepPreviousData
  });

  const earners = data?.results ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(Math.ceil(total / PER_PAGE), 1);
  const firstRank = (page - 1) * PER_PAGE + 1;

  return (
    <section className="aqt-card-surface min-w-0">
      <div className="aqt-card-head">
        <div className="aqt-card-title">
          <span className="aqt-card-title-ic">
            <Users size={15} aria-hidden />
          </span>
          <span>{t("achievements.detail.earnedBy")}</span>
        </div>
        {total > 0 ? (
          <span className="aqt-card-sub tabular-nums">
            {t("achievements.detail.earnersCount", { count: total })}
          </span>
        ) : null}
      </div>

      {isError ? (
        <div className="aqt-card-body text-center text-sm text-[color:var(--aqt-fg-muted)]">
          {t("common.loadError")}
        </div>
      ) : isLoading ? (
        <div>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="aqt-earner-row">
              <Skeleton className="h-4 w-5 justify-self-end" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-8 justify-self-end" />
            </div>
          ))}
        </div>
      ) : earners.length === 0 ? (
        <div className="aqt-card-body text-center text-sm text-[color:var(--aqt-fg-dim)]">
          {t("achievements.detail.noEarners")}
        </div>
      ) : (
        <div>
          {earners.map((earned, i) => (
            <div key={`${earned.user.id}-${i}`} className="aqt-earner-row">
              <span className="aqt-earner-rank tabular-nums">{firstRank + i}</span>
              <div className="min-w-0">
                <PlayerName player={earned.user} includeSpecialization={false} />
                {(earned.last_tournament || earned.last_match) && (
                  <div className="aqt-earner-meta">
                    {earned.last_tournament ? (
                      <Link
                        href={`/tournaments/${earned.last_tournament.id}`}
                        className="inline-flex items-center gap-1.5"
                      >
                        <Trophy size={12} aria-hidden />
                        <span className="truncate">{earned.last_tournament.name}</span>
                      </Link>
                    ) : null}
                    {earned.last_match ? (
                      <Link
                        href={`/matches/${earned.last_match.id}`}
                        className="inline-flex items-center gap-1.5"
                      >
                        <Swords size={12} aria-hidden />
                        <span className="inline-flex min-w-0 items-center gap-1 truncate">
                          <TeamName team={earned.last_match.home_team} size="xs" fallback="?" />
                          {t("common.vs")}
                          <TeamName team={earned.last_match.away_team} size="xs" fallback="?" />
                        </span>
                      </Link>
                    ) : null}
                  </div>
                )}
              </div>
              <span className="aqt-earner-count tabular-nums">×{earned.count}</span>
            </div>
          ))}

          <DataPagination
            page={page}
            totalPages={totalPages}
            onPageChange={setPage}
            className="border-t border-[color:var(--aqt-border)] p-4"
          />
        </div>
      )}
    </section>
  );
};

export default AchievementUsers;

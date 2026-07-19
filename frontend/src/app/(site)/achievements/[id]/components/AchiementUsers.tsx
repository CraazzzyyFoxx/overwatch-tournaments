"use client";

import React, { useEffect, useMemo } from "react";
import Link from "next/link";
import { Swords, Trophy, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useInfiniteQuery } from "@tanstack/react-query";

import { Achievement } from "@/types/achievement.types";
import achievementsService from "@/services/achievements.service";
import PlayerName from "@/components/PlayerName";
import { Skeleton } from "@/components/ui/skeleton";

const PER_PAGE = 30;

const AchievementUsers = ({ achievement }: { achievement: Achievement }) => {
  const t = useTranslations();

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading, isError } =
    useInfiniteQuery({
    queryKey: ["achievement", "users", achievement.id],
    queryFn: ({ pageParam }) => achievementsService.getUsers(achievement.id, pageParam, PER_PAGE),
    initialPageParam: 1,
    getNextPageParam: (lastPage) =>
      lastPage.total / lastPage.per_page > lastPage.page ? lastPage.page + 1 : undefined
  });

  const earners = useMemo(() => data?.pages.flatMap((p) => p.results) ?? [], [data?.pages]);
  const total = data?.pages[0]?.total ?? 0;

  // Infinite scroll: fetch the next page as the viewport nears the document end.
  useEffect(() => {
    const onScroll = () => {
      const nearBottom =
        window.innerHeight + document.documentElement.scrollTop >=
        document.documentElement.offsetHeight - 400;
      if (nearBottom && hasNextPage && !isFetchingNextPage) {
        void fetchNextPage();
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <section className="aqt-card-surface min-w-0">
      <div className="aqt-card-head">
        <div className="aqt-card-title">
          <span className="aqt-card-title-ic">
            <Users size={15} />
          </span>
          <span>{t("achievements.detail.earnedBy")}</span>
        </div>
        {total > 0 ? (
          <span className="aqt-card-sub">
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
              <span className="aqt-earner-rank">{i + 1}</span>
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
                        <span className="truncate">
                          {earned.last_match.home_team?.name ?? "?"} {t("common.vs")}{" "}
                          {earned.last_match.away_team?.name ?? "?"}
                        </span>
                      </Link>
                    ) : null}
                  </div>
                )}
              </div>
              <span className="aqt-earner-count">×{earned.count}</span>
            </div>
          ))}

          {hasNextPage ? (
            <div className="flex justify-center border-t border-[color:var(--aqt-border)] p-4">
              <button
                type="button"
                onClick={() => fetchNextPage()}
                disabled={isFetchingNextPage}
                className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.02)] px-4 py-1.5 text-[12px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-border-3)] hover:text-[color:var(--aqt-fg)] disabled:opacity-50"
              >
                {t("common.loadMore")}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
};

export default AchievementUsers;

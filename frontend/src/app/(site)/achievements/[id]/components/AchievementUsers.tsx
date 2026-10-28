"use client";

import { Fragment, useState } from "react";
import Link from "next/link";
import { Swords, Trophy } from "lucide-react";
import { useTranslations } from "next-intl";
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { Achievement } from "@/types/achievement.types";
import achievementsService from "@/services/achievements.service";
import PlayerName from "@/components/PlayerName";
import TeamName from "@/components/TeamName";
import { DataPagination } from "@/components/ui/data-pagination";
import { CardSurface } from "@/components/profile/atoms";
import { Skeleton } from "@/components/ui/skeleton";
import { achievementQueryKeys } from "@/lib/achievements/query-keys";
import type { StatsScope } from "@/lib/site/stats-scope";

const PER_PAGE = 30;

const ROW =
  "grid grid-cols-[34px_1fr_auto] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-4.5 py-2.75 transition-colors last:border-b-0 hover:bg-[color:var(--aqt-overlay-2)]";
const META_LINK =
  "inline-flex items-center gap-1.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-teal)] [&_svg]:shrink-0 [&_svg]:opacity-65";

const AchievementUsers = ({ achievement, scope }: { achievement: Achievement; scope: StatsScope }) => {
  const t = useTranslations();
  const [page, setPage] = useState(1);

  const { data, isLoading, isError } = useQuery({
    queryKey: achievementQueryKeys.users(achievement.id, scope, page),
    queryFn: () => achievementsService.getUsers(achievement.id, page, PER_PAGE, scope),
    placeholderData: keepPreviousData
  });

  const earners = data?.results ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(Math.ceil(total / PER_PAGE), 1);
  const firstRank = (page - 1) * PER_PAGE + 1;

  return (
    <CardSurface
      className="min-w-0"
      title={t("achievements.detail.earnedBy")}
      subtitle={total > 0 ? t("achievements.detail.earnersCount", { count: total }) : undefined}
      flush={!isError && (isLoading || earners.length > 0)}
    >
      {isError ? (
        <p className="text-center text-sm text-[color:var(--aqt-fg-muted)]">{t("common.loadError")}</p>
      ) : isLoading ? (
        <div>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className={ROW}>
              <Skeleton className="h-4 w-5 justify-self-end" />
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-4 w-8 justify-self-end" />
            </div>
          ))}
        </div>
      ) : earners.length === 0 ? (
        <p className="text-center text-sm text-[color:var(--aqt-fg-dim)]">{t("achievements.detail.noEarners")}</p>
      ) : (
        <div>
          {earners.map((earned, i) => (
            <div key={`${earned.user.id}-${i}`} className={ROW}>
              <span className="aqt-tnum text-right text-label font-bold text-[color:var(--aqt-fg-faint)]">{firstRank + i}</span>
              <div className="min-w-0">
                <PlayerName player={earned.user} includeSpecialization={false} />
                {(earned.last_tournament || earned.last_match) && (
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-[color:var(--aqt-fg-dim)]">
                    {earned.last_tournament ? (
                      <Link href={`/tournaments/${earned.last_tournament.id}`} className={META_LINK}>
                        <Trophy size={12} aria-hidden />
                        <span className="truncate">{earned.last_tournament.name}</span>
                      </Link>
                    ) : null}
                    {earned.last_match ? (
                      <Link href={`/matches/${earned.last_match.id}`} className={META_LINK}>
                        <Swords size={12} aria-hidden />
                        <span className="inline-flex min-w-0 items-center gap-1 truncate">
                          {earned.last_match.participants.map((participant, index) => (
                            <Fragment key={participant.encounter_team_id}>
                              {index > 0 ? t("common.vs") : null}
                              <TeamName team={{ name: participant.name }} size="xs" fallback="?" />
                            </Fragment>
                          ))}
                        </span>
                      </Link>
                    ) : null}
                  </div>
                )}
              </div>
              <span className="aqt-tnum font-bold text-[color:var(--aqt-teal)]">×{earned.count}</span>
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
    </CardSurface>
  );
};

export default AchievementUsers;

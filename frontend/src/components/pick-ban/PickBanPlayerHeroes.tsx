"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { Button } from "@/components/ui/button";
import { useCurrentWorkspaceId } from "@/hooks/useCurrentWorkspace";
import { userQueryKeys } from "@/lib/users/query-keys";
import userService from "@/services/user.service";
import { LogStatsName } from "@/types/stats.types";
import type { Player } from "@/types/team.types";

const HERO_STATS = [LogStatsName.HeroTimePlayed];

export function PickBanPlayerHeroes({ player }: Readonly<{ player: Player | undefined }>) {
  const t = useTranslations("pickBan.room.playerHeroes");
  const workspaceId = useCurrentWorkspaceId();
  const userId = player?.user_id ?? 0;
  const hasUser = Number.isFinite(userId) && userId > 0;
  const history = useQuery({
    // A playtime-only response must not replace the profile's full-stat cache.
    queryKey: [...userQueryKeys.heroes(userId, undefined), HERO_STATS, workspaceId],
    queryFn: () => userService.getUserHeroes(userId, HERO_STATS),
    enabled: hasUser && workspaceId != null,
    staleTime: 5 * 60 * 1000
  });
  const heroes = useMemo(
    () =>
      (history.data?.results ?? [])
        .map(({ hero, stats }) => ({
          hero,
          playtime: stats.find((stat) => stat.name === LogStatsName.HeroTimePlayed)?.overall ?? 0
        }))
        .filter(({ playtime }) => Number.isFinite(playtime) && playtime > 0)
        .sort((a, b) => b.playtime - a.playtime || a.hero.id - b.hero.id),
    [history.data]
  );

  return (
    <div className="min-w-0 px-3 pb-2.5">
      {!hasUser ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("noUser")}</p>
      ) : workspaceId == null ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("noWorkspace")}</p>
      ) : history.isPending ? (
        <p role="status" className="text-xs text-[color:var(--aqt-fg-muted)]">
          {t("loading")}
        </p>
      ) : history.isError ? (
        <div className="flex flex-wrap items-center gap-2">
          <p role="status" className="text-xs text-[color:var(--aqt-fg-muted)]">
            {t("error")}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={history.isFetching}
            onClick={() => void history.refetch()}
          >
            {t("retry")}
          </Button>
        </div>
      ) : heroes.length === 0 ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("empty")}</p>
      ) : (
        <ul
          aria-label={t("title")}
          tabIndex={0}
          className="flex max-h-32 flex-wrap gap-2 overflow-y-auto"
        >
          {heroes.map(({ hero, playtime }) => (
            <li
              key={hero.id}
              className="flex max-w-full items-center gap-2 rounded-lg bg-[color:var(--aqt-card-2)] px-2 py-1.5"
            >
              <PickBanItemThumb kind="hero" item={hero} name={hero.name} size={24} />
              <span className="min-w-0 text-xs">
                <span className="block break-words font-medium text-[color:var(--aqt-fg)]">
                  {hero.name}
                </span>
                <span className="block tabular-nums text-[color:var(--aqt-fg-muted)]">
                  {t("playtime", { minutes: Math.round(playtime / 6) / 10 })}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

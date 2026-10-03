"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { PickBanItemThumb } from "@/components/pick-ban/PickBanItemThumb";
import { Button } from "@/components/ui/button";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import encounterService from "@/services/encounter.service";

export function PickBanPlayerHeroes({
  playerId,
  matchId
}: Readonly<{ playerId: number; matchId: number | null }>) {
  const t = useTranslations("pickBan.room.playerHeroes");
  const history = useQuery({
    queryKey: encounterQueryKeys.matchDetail(matchId),
    queryFn: () => encounterService.getMatch(matchId!),
    enabled: matchId != null
  });
  const heroes = useMemo(() => {
    const match = history.data;
    const player = [match?.home_team, match?.away_team]
      .flatMap((team) => team?.players ?? [])
      .find((candidate) => candidate.id === playerId);
    return [...new Map(Object.values(player?.heroes ?? {}).flat().map((hero) => [hero.id, hero])).values()];
  }, [history.data, playerId]);

  return (
    <div className="min-w-0 px-3 pb-2.5">
      {matchId == null ? (
        <p className="text-xs text-[color:var(--aqt-fg-muted)]">{t("noLog")}</p>
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
          {heroes.map((hero) => (
            <li
              key={hero.id}
              className="flex max-w-full items-center gap-2 rounded-lg bg-[color:var(--aqt-card-2)] px-2 py-1.5"
            >
              <PickBanItemThumb kind="hero" item={hero} name={hero.name} size={24} />
              <span className="min-w-0 break-words text-xs font-medium text-[color:var(--aqt-fg)]">
                {hero.name}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

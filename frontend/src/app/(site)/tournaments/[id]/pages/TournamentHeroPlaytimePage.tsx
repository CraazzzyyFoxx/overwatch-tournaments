"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Skeleton } from "@/components/ui/skeleton";
import { Tournament } from "@/types/tournament.types";
import type { HeroPlaytime } from "@/types/hero.types";
import heroService from "@/services/hero.service";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

import { useTranslation } from "@/i18n/LanguageContext";

type RoleKey = "tank" | "dps" | "support";
type RoleFilter = "all" | RoleKey;

const ROLE_ORDER: RoleKey[] = ["tank", "dps", "support"];

function heroRole(playtime: HeroPlaytime): RoleKey {
  const raw = (playtime.hero.type ?? playtime.hero.role ?? "").toLowerCase();
  if (raw.startsWith("tank")) return "tank";
  if (raw.startsWith("sup")) return "support";
  return "dps";
}

const TournamentHeroPlaytimePage = ({ tournament }: { tournament: Tournament }) => {
  const { t } = useTranslation();
  const statsQuery = useQuery({
    queryKey: tournamentQueryKeys.heroPlaytime(tournament.id),
    queryFn: () =>
      heroService.getHeroPlaytime(1, -1, "all", tournament.id, {
        workspaceId: tournament.workspace_id,
      }),
  });

  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");

  const heroes = useMemo(
    () => [...(statsQuery.data?.results ?? [])].sort((a, b) => b.playtime - a.playtime),
    [statsQuery.data],
  );

  const roleCounts = useMemo(() => {
    const counts: Record<RoleKey, number> = { tank: 0, dps: 0, support: 0 };
    for (const hero of heroes) counts[heroRole(hero)] += 1;
    return counts;
  }, [heroes]);

  const maxPlaytime = heroes.length ? heroes[0].playtime : 0;
  const visible =
    roleFilter === "all" ? heroes : heroes.filter((hero) => heroRole(hero) === roleFilter);

  if (statsQuery.isLoading) {
    return <Skeleton className="h-[420px] w-full rounded-xl" />;
  }

  return (
    <div className="space-y-4">
      <div className="section-head">
        <h2>
          {t("common.heroes")} <span className="count-tag">{heroes.length}</span>
        </h2>
        <span className="meta">{t("common.byPlaytime")}</span>
      </div>

      {heroes.length > 0 && (
        <div className="filters">
          <button
            type="button"
            className={cn("filter-chip", roleFilter === "all" && "active")}
            onClick={() => setRoleFilter("all")}
          >
            {t("common.all")} <span className="count">{heroes.length}</span>
          </button>
          {ROLE_ORDER.filter((role) => roleCounts[role] > 0).map((role) => (
            <button
              key={role}
              type="button"
              className={cn("filter-chip", roleFilter === role && "active")}
              onClick={() => setRoleFilter(role)}
            >
              {t("common.roles." + role)} <span className="count">{roleCounts[role]}</span>
            </button>
          ))}
        </div>
      )}

      {visible.length > 0 ? (
        <div className="tn-card" style={{ padding: 18 }}>
          <div className="hero-bars">
            {visible.map((hero) => {
              const role = heroRole(hero);
              const sharePct = hero.playtime * 100;
              const barWidth = maxPlaytime > 0 ? (hero.playtime / maxPlaytime) * 100 : 0;
              return (
                <div className="hero-row" key={hero.hero.id}>
                  <div className="hero-name">
                    <Avatar className="h-[34px] w-[34px] bg-transparent border-none">
                      {hero.hero.image_path && (
                        <AvatarImage
                          src={hero.hero.image_path}
                          alt={hero.hero.name}
                          className="object-contain"
                        />
                      )}
                      <AvatarFallback className="bg-transparent" />
                    </Avatar>
                    <div className="stack">
                      <span className="nm">{hero.hero.name}</span>
                      <span className="meta">{t("common.roles." + role)}</span>
                    </div>
                  </div>
                  <div className="hero-bar">
                    <div
                      className={cn("fill", !hero.hero.color && role)}
                      style={{
                        width: `${barWidth}%`,
                        backgroundColor: hero.hero.color || undefined
                      }}
                    />
                  </div>
                  <div className="hero-stats">
                    <span className="val">{sharePct.toFixed(1)}</span>
                    <span className="pct">{t("common.playtimeLabel")}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="tn-card" style={{ padding: "48px 24px", textAlign: "center", color: "var(--fg-dim)" }}>
          {t("common.noHeroData")}
        </div>
      )}
    </div>
  );
};


export default TournamentHeroPlaytimePage;

"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import { cn } from "@/lib/utils";
import heroService from "@/services/hero.service";
import type { HeroPlaytime } from "@/types/hero.types";

import styles from "../TournamentDetail.module.css";
import { TournamentPageState } from "../_components/TournamentPageState";
import { TournamentHeroesSkeleton } from "../_components/TournamentSkeletons";
import { useTournamentQuery } from "../_hooks/useTournamentClientData";
import {
  getPublicPageQueryPresentation,
  type PublicPageQueryState
} from "./publicPageQueryPresentation";

type RoleKey = "tank" | "dps" | "support";
type RoleFilter = "all" | RoleKey;

const ROLE_ORDER: RoleKey[] = ["tank", "dps", "support"];

export const getHeroesQueryPresentation = (state: PublicPageQueryState) =>
  getPublicPageQueryPresentation(state);

function heroRole(playtime: HeroPlaytime): RoleKey {
  const raw = (playtime.hero.type ?? playtime.hero.role ?? "").toLowerCase();
  if (raw.startsWith("tank")) return "tank";
  if (raw.startsWith("sup")) return "support";
  return "dps";
}

const TournamentHeroPlaytimePage = ({ tournamentId }: { tournamentId: number }) => {
  const t = useTranslations();
  const tournamentQuery = useTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;
  const statsQuery = useQuery({
    queryKey: tournamentQueryKeys.heroPlaytime(tournamentId),
    queryFn: () => {
      if (!tournament) throw new Error("Tournament overview is required");
      return heroService.getHeroPlaytime(1, -1, "all", tournament.id, {
        workspaceId: tournament.workspace_id
      });
    },
    enabled: tournament !== undefined
  });
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");

  const heroes = useMemo(
    () =>
      statsQuery.data ? [...statsQuery.data.results].sort((a, b) => b.playtime - a.playtime) : [],
    [statsQuery.data]
  );
  const roleCounts = useMemo(() => {
    const counts: Record<RoleKey, number> = { tank: 0, dps: 0, support: 0 };
    for (const hero of heroes) counts[heroRole(hero)] += 1;
    return counts;
  }, [heroes]);
  const maxPlaytime = heroes.length ? Math.max(0, heroes[0].playtime) : 0;
  const visible =
    roleFilter === "all" ? heroes : heroes.filter((hero) => heroRole(hero) === roleFilter);
  const presentation = getHeroesQueryPresentation({
    data: statsQuery.data,
    itemCount: heroes.length,
    isPending: statsQuery.isPending,
    isError: statsQuery.isError,
    isFetching: statsQuery.isFetching
  });

  if (!tournament) {
    if (tournamentQuery.isError) {
      return (
        <TournamentPageState state="initial-error" onRetry={() => void tournamentQuery.refetch()} />
      );
    }
    return <TournamentHeroesSkeleton />;
  }

  if (presentation.initialState === "error") {
    return <TournamentPageState state="initial-error" onRetry={() => void statsQuery.refetch()} />;
  }
  if (presentation.initialState === "skeleton" || presentation.contentState === null) {
    return <TournamentHeroesSkeleton />;
  }

  const content = (
    <section className={styles.publicDataPage} aria-labelledby="tournament-heroes-title">
      <header className={styles.pageHeading}>
        <div className={styles.pageHeadingCopy}>
          <span className={styles.pageEyebrow}>
            {t("tournamentDetail.publicPages.heroes.eyebrow")}
          </span>
          <div className={styles.pageTitleRow}>
            <h2 className={styles.pageTitle} id="tournament-heroes-title">
              {t("common.heroes")}
            </h2>
            <span className={styles.pageCount}>{heroes.length}</span>
          </div>
          <p className={styles.pageContext}>{t("tournamentDetail.publicPages.heroes.context")}</p>
        </div>
        {presentation.showUpdating ? (
          <span className={styles.updating} role="status" aria-live="polite">
            {t("tournamentDetail.pageState.updating")}
          </span>
        ) : null}
      </header>

      {heroes.length > 0 ? (
        <div
          className={styles.controlRail}
          role="group"
          aria-label={t("tournamentDetail.publicPages.heroes.roleLabel")}
        >
          <button
            type="button"
            className={cn("filter-chip", roleFilter === "all" && "active")}
            aria-pressed={roleFilter === "all"}
            onClick={() => setRoleFilter("all")}
          >
            {t("common.all")} <span className="count">{heroes.length}</span>
          </button>
          {ROLE_ORDER.filter((role) => roleCounts[role] > 0).map((role) => (
            <button
              key={role}
              type="button"
              className={cn("filter-chip", roleFilter === role && "active")}
              aria-pressed={roleFilter === role}
              onClick={() => setRoleFilter(role)}
            >
              {t(`common.roles.${role}`)} <span className="count">{roleCounts[role]}</span>
            </button>
          ))}
        </div>
      ) : null}

      {presentation.contentState === "empty" ? (
        <TournamentPageState
          state="empty"
          title={t("tournamentDetail.publicPages.heroes.emptyTitle")}
          description={t("tournamentDetail.publicPages.heroes.emptyDescription")}
        />
      ) : visible.length === 0 ? (
        <TournamentPageState state="filtered-empty" onReset={() => setRoleFilter("all")} />
      ) : (
        <div className={cn("tn-card", styles.heroList)}>
          <div className="hero-bars">
            {visible.map((hero, index) => {
              const role = heroRole(hero);
              const sharePct = Math.max(0, hero.playtime * 100);
              const barWidth =
                maxPlaytime > 0 ? Math.min(100, (hero.playtime / maxPlaytime) * 100) : 0;
              return (
                <div className="hero-row" key={hero.hero.id} data-rank={index + 1}>
                  <div className="hero-name">
                    <span className={styles.heroRank} aria-hidden="true">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <Avatar className="h-[34px] w-[34px] border-none bg-transparent">
                      {hero.hero.image_path ? (
                        <AvatarImage
                          src={hero.hero.image_path}
                          alt={hero.hero.name}
                          className="object-contain"
                        />
                      ) : null}
                      <AvatarFallback className="bg-transparent" />
                    </Avatar>
                    <div className="stack">
                      <span className="nm">{hero.hero.name}</span>
                      <span className="meta">{t(`common.roles.${role}`)}</span>
                    </div>
                  </div>
                  <div
                    className="hero-bar"
                    role="progressbar"
                    aria-label={`${hero.hero.name}: ${sharePct.toFixed(1)} ${t("common.playtimeLabel")}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Number(Math.min(100, sharePct).toFixed(1))}
                    aria-valuetext={`${sharePct.toFixed(1)} ${t("common.playtimeLabel")}`}
                  >
                    <div
                      className={cn(
                        "fill",
                        styles.heroBarFill,
                        !hero.hero.color && role,
                        barWidth === 0 && styles.zeroHeroBar
                      )}
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
      )}
    </section>
  );

  if (presentation.showRefreshError) {
    return (
      <TournamentPageState
        state="refresh-error"
        onRetry={() => void statsQuery.refetch()}
        isUpdating={statsQuery.isFetching}
      >
        {content}
      </TournamentPageState>
    );
  }

  return content;
};

export default TournamentHeroPlaytimePage;

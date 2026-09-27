"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { PageHero, HeroCoord } from "@/components/site/PageHero";
import type { UserOverviewStats } from "@/types/user.types";

import styles from "./Users.module.css";

/** Roster headline plus the four platform-wide counters, once stats land. */
export function UsersIndexHero({ stats }: Readonly<{ stats: UserOverviewStats | undefined }>) {
  const t = useTranslations();
  const format = useFormatter();

  return (
    <PageHero
      eyebrow={
        <HeroCoord>
          <HoverPrefetchLink
            href="/"
            className="transition-colors hover:text-[color:var(--aqt-teal)]"
          >
            {t("users.list.hero.eyebrowRoster")}
          </HoverPrefetchLink>{" "}
          · {t("users.list.hero.eyebrowCurrent")}
        </HeroCoord>
      }
      title={t.rich("users.list.hero.title", { em: (chunks) => <em>{chunks}</em> })}
      lede={t("users.list.hero.lede")}
      aside={
        <div className={styles.heroStats}>
          <div className={styles.heroStat}>
            <span className={styles.statLabel}>{t("users.list.stats.totalPlayers")}</span>
            <span className={styles.statValue}>
              {stats ? format.number(stats.total_players) : "-"}
            </span>
            <span className={styles.statSub}>
              {stats
                ? t("users.list.stats.roleBreakdown", {
                    tank: String(stats.tank_count),
                    damage: String(stats.damage_count),
                    support: String(stats.support_count)
                  })
                : t("common.loading")}
            </span>
          </div>
          <div className={styles.heroStat}>
            <span className={styles.statLabel}>{t("users.list.stats.withLogs")}</span>
            <span className={styles.statValue}>
              {stats ? Math.round(stats.with_logs_pct) : "-"}
              <em>%</em>
            </span>
            <span className={styles.statSub}>
              {stats
                ? t("users.list.stats.withParsedGames", {
                    count: format.number(stats.with_logs_count)
                  })
                : "—"}
            </span>
          </div>
          <div className={styles.heroStat}>
            <span className={styles.statLabel}>
              {t("users.list.stats.avgTournamentsPerPlayer")}
            </span>
            <span className={styles.statValue}>
              {stats ? stats.avg_tournaments_per_player.toFixed(1) : "-"}
            </span>
            <span className={styles.statSub}>
              {stats
                ? t("users.list.stats.median", {
                    value: stats.median_tournaments_per_player.toFixed(0)
                  })
                : "—"}
            </span>
          </div>
          <div className={styles.heroStat}>
            <span className={styles.statLabel}>{t("users.list.stats.activeLast30d")}</span>
            <span className={styles.statValue}>
              {stats ? format.number(stats.active_last_30d) : "-"}
            </span>
            <span className={styles.statSub}>
              {stats
                ? t("users.list.stats.ofRoster", {
                    pct: String(Math.round(stats.active_last_30d_pct))
                  })
                : "—"}
            </span>
          </div>
        </div>
      }
    />
  );
}

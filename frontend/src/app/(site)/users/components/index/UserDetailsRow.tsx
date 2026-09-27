"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import {
  formatOptional,
  formatPlaytime,
  HERO_METRIC_LABEL_KEYS
} from "@/app/(site)/users/components/shared/list-utils";
import type { UserOverviewRow } from "@/types/user.types";

import styles from "./Users.module.css";

/** The row a player's "details" toggle opens: their averages and hero cards. */
export function UserDetailsRow({ user }: Readonly<{ user: UserOverviewRow }>) {
  const t = useTranslations();

  return (
    <tr className={styles.expandRow}>
      <td colSpan={7}>
        <div className={styles.exGrid}>
          <div className={styles.exStat}>
            <span className={styles.exStatLabel}>{t("users.list.expanded.avgPlacement")}</span>
            <span className={styles.exStatValue}>
              {formatOptional(user.averages.avg_placement)}
            </span>
          </div>
          <div className={styles.exStat}>
            <span className={styles.exStatLabel}>{t("users.list.expanded.avgPlayoff")}</span>
            <span className={styles.exStatValue}>
              {formatOptional(user.averages.avg_playoff_placement)}
            </span>
          </div>
          <div className={styles.exStat}>
            <span className={styles.exStatLabel}>{t("users.list.expanded.avgGroup")}</span>
            <span className={styles.exStatValue}>
              {formatOptional(user.averages.avg_group_placement)}
            </span>
          </div>
          <div className={styles.exStat}>
            <span className={styles.exStatLabel}>{t("users.list.expanded.avgCloseness")}</span>
            <span className={styles.exStatValue}>
              {formatOptional(user.averages.avg_closeness)}
            </span>
          </div>
        </div>
        <div className={styles.exSectionTitle}>{t("users.list.expanded.topHeroesDetails")}</div>
        <p className={styles.exSectionNote}>{t("users.list.expanded.metricsNote")}</p>
        {user.top_heroes.length === 0 ? (
          <p className={styles.playerSub}>{t("users.list.expanded.noHeroData")}</p>
        ) : (
          <div className={styles.heroCards}>
            {user.top_heroes.map((heroRow) => (
              <div key={`${user.id}-${heroRow.hero.id}`} className={styles.heroCard}>
                <div className={styles.heroCardTop}>
                  <div className={styles.heroCardAvatar}>
                    <Image
                      src={heroRow.hero.image_path}
                      alt={heroRow.hero.name}
                      width={40}
                      height={40}
                      className="object-contain select-none"
                    />
                  </div>
                  <div className={styles.heroCardStack}>
                    <span className={styles.heroCardName}>{heroRow.hero.name}</span>
                    <span className={styles.heroCardPlaytime}>
                      {t("users.list.expanded.playtime", {
                        value: formatPlaytime(heroRow.playtime_seconds, t)
                      })}
                    </span>
                  </div>
                </div>
                <div className={styles.heroCardMetrics}>
                  {heroRow.metrics.length === 0 ? (
                    <span className={styles.playerSub}>{t("users.list.expanded.noMetrics")}</span>
                  ) : (
                    heroRow.metrics.map((metric) => {
                      const metricKey = HERO_METRIC_LABEL_KEYS[metric.name];
                      return (
                        <span
                          key={`${heroRow.hero.id}-${metric.name}`}
                          className={styles.metricBadge}
                        >
                          <span className={styles.metricBadgeKey}>
                            {metricKey ? t(metricKey) : metric.name}
                          </span>
                          <span className={styles.metricBadgeValue}>
                            {metric.avg_10.toFixed(2)}
                          </span>
                        </span>
                      );
                    })
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

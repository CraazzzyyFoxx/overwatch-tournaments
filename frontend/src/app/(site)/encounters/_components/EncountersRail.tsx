"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { cn } from "@/lib/utils";
import type { EncounterOverview } from "@/types/encounter.types";

import { formatDuration } from "./encounters.helpers";
import { countLabel } from "./encounters.model";
import styles from "./Encounters.module.css";

/** Side rail beside the list: series pulse, hot maps and the side balance. */
export function EncountersRail({ overview }: Readonly<{ overview: EncounterOverview }>) {
  const t = useTranslations();
  const format = useFormatter();
  const maxMapCount = Math.max(1, ...overview.hot_maps.map((map) => map.count));

  return (
    <aside className={styles.rail}>
      <div className={styles.card}>
        <div className={styles.cardHead}>
          <div className={styles.cardTitle}>{t("encounters.pulse.title")}</div>
        </div>
        <div className={styles.insightList}>
          <Insight
            label={t("encounters.pulse.avgLength")}
            value={formatDuration(overview.pulse.avg_series_seconds)}
            meta={t("encounters.pulse.avgLengthMeta", {
              count: countLabel(format, overview.pulse.completed_series_count)
            })}
          />
          <Insight
            label={t("encounters.pulse.sweepRate")}
            value={`${overview.pulse.sweep_rate}%`}
            meta={t("encounters.pulse.sweepMeta", {
              sweeps: countLabel(format, overview.pulse.sweep_count),
              distance: countLabel(format, overview.pulse.went_distance_count)
            })}
          />
          <Insight
            label={t("encounters.pulse.reverseSweepRate")}
            value={`${overview.pulse.reverse_sweep_rate}%`}
            meta={t("encounters.pulse.reverseSweepMeta")}
          />
          <Insight
            label={t("encounters.pulse.mostDecisiveMap")}
            value={overview.pulse.most_decisive_map ?? "—"}
            valueClassName={styles.insightValueSmall}
          />
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardHead}>
          <div className={styles.cardTitle}>{t("encounters.hotMaps.title")}</div>
          <span className={styles.cardSub}>{t("encounters.hotMaps.sub")}</span>
        </div>
        <div>
          {overview.hot_maps.length ? (
            overview.hot_maps.map((map) => (
              <div key={map.name} className={styles.mapRow}>
                <span className={styles.mapName}>{map.name}</span>
                <div aria-hidden className={styles.mapTrack}>
                  <div
                    className={styles.mapFill}
                    style={{ width: `${(map.count / maxMapCount) * 100}%` }}
                  />
                </div>
                <span className={cn(styles.mapNum, "tabular-nums")}>
                  {countLabel(format, map.count)}
                </span>
              </div>
            ))
          ) : (
            <div className={styles.empty}>{t("encounters.hotMaps.empty")}</div>
          )}
        </div>
      </div>

      <div className={styles.card}>
        <div className={styles.cardHead}>
          <div className={styles.cardTitle}>{t("encounters.sideBalance.title")}</div>
          <span className={styles.cardSub}>{t("encounters.sideBalance.sub")}</span>
        </div>
        <div className={styles.cardBody}>
          <div className={styles.balance}>
            <div
              className={cn(styles.balanceHome, "tabular-nums")}
              style={{ width: `${overview.side_balance.home_win_pct}%` }}
            >
              {overview.side_balance.home_win_pct}%
            </div>
            <div
              className={cn(styles.balanceAway, "tabular-nums")}
              style={{ width: `${overview.side_balance.away_win_pct}%` }}
            >
              {overview.side_balance.away_win_pct}%
            </div>
          </div>
          <div className={styles.balanceLegend}>
            <span>
              <span aria-hidden className={styles.balanceLegendHome}>
                ●{" "}
              </span>
              {t("encounters.sideBalance.homeWins")}
            </span>
            <span>
              {t("encounters.sideBalance.awayWins")}{" "}
              <span aria-hidden className={styles.dim}>
                ●
              </span>
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}

function Insight({
  label,
  value,
  meta,
  valueClassName
}: Readonly<{
  label: string;
  value: string;
  meta?: string;
  valueClassName?: string;
}>) {
  return (
    <div className={styles.insightRow}>
      <span className={styles.insightLabel}>{label}</span>
      <span className={cn(styles.insightValue, "tabular-nums", valueClassName)}>{value}</span>
      {meta ? <span className={styles.insightMeta}>{meta}</span> : null}
    </div>
  );
}

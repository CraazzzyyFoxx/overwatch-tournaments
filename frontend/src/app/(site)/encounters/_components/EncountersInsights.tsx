"use client";

import { useMemo, type CSSProperties } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { cn } from "@/lib/utils";
import type { EncounterOverview } from "@/types/encounter.types";

import { formatPercent } from "./encounters.helpers";
import { buildHeatmapMatrix, countLabel, donutSegments } from "./encounters.model";
import styles from "./Encounters.module.css";

/** Closeness histogram, final-score heatmap and the stage split donut. */
export function EncountersInsights({ overview }: Readonly<{ overview: EncounterOverview }>) {
  const t = useTranslations();
  const format = useFormatter();
  const maxHistogram = Math.max(1, ...overview.closeness_histogram.map((bucket) => bucket.count));
  const heatmap = useMemo(
    () => buildHeatmapMatrix(overview.score_heatmap),
    [overview.score_heatmap]
  );
  const stageDonut = useMemo(() => donutSegments(overview.stage_split), [overview.stage_split]);

  return (
    <section aria-label={t("encounters.insights.title")}>
      <div className={styles.sectionHead}>
        <h2 className={styles.sectionTitle}>{t("encounters.insights.title")}</h2>
        <span className={styles.sectionMeta}>
          {t("encounters.insights.meta", {
            count: overview.pulse.completed_series_count
          })}
        </span>
      </div>
      <div className={styles.grid3}>
        <div className={styles.card}>
          <div className={styles.cardHead}>
            <div>
              <div className={styles.cardTitle}>{t("encounters.insights.closenessTitle")}</div>
              <div className={styles.cardSub}>{t("encounters.insights.closenessSub")}</div>
            </div>
            <span className={styles.pill}>
              {t("encounters.insights.avg")}{" "}
              <span className={cn(styles.mono, styles.pillAccent)}>
                {formatPercent(overview.kpis.avg_closeness)}
              </span>
            </span>
          </div>
          <div className={styles.cardBody}>
            <div className={styles.hist}>
              {overview.closeness_histogram.map((bucket) => (
                <div
                  key={bucket.label}
                  className={styles.histBar}
                  aria-label={`${bucket.label}: ${bucket.count}`}
                  style={{ height: `${Math.max(6, (bucket.count / maxHistogram) * 100)}%` }}
                >
                  <span className={styles.histBarValue}>{bucket.count}</span>
                </div>
              ))}
            </div>
            <div className={styles.histAxis}>
              <span>0%</span>
              <span>20%</span>
              <span>40%</span>
              <span>60%</span>
              <span>80%</span>
              <span>100%</span>
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHead}>
            <div>
              <div className={styles.cardTitle}>{t("encounters.insights.scoreTitle")}</div>
              <div className={styles.cardSub}>{t("encounters.insights.scoreSub")}</div>
            </div>
            <span className={styles.pill}>
              {t("encounters.insights.max")}{" "}
              <span className={cn(styles.mono, styles.pillAccent)}>
                {countLabel(format, heatmap.max)}
              </span>
            </span>
          </div>
          <div className={styles.cardBody}>
            <div className={styles.scoreGrid}>
              <div />
              {heatmap.cols.map((col) => (
                <div key={`col-${col}`} className={styles.scoreHeader}>
                  {col}
                </div>
              ))}
              {heatmap.rows.map((row) => (
                <RowCells
                  key={`row-${row}`}
                  row={row}
                  cols={heatmap.cols}
                  matrix={heatmap.matrix}
                  max={heatmap.max}
                />
              ))}
            </div>
            <div className={styles.scoreLegend}>
              <span>{t("encounters.insights.fewer")}</span>
              <span aria-hidden className={styles.scoreLegendGrad} />
              <span>{t("encounters.insights.more")}</span>
            </div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardHead}>
            <div>
              <div className={styles.cardTitle}>{t("encounters.insights.byStageTitle")}</div>
              <div className={styles.cardSub}>{t("encounters.insights.byStageSub")}</div>
            </div>
          </div>
          <div className={styles.cardBody}>
            <div className={styles.donutRow}>
              <div className={styles.donut}>
                <svg width="140" height="140" viewBox="0 0 140 140" aria-hidden>
                  <circle
                    cx="70"
                    cy="70"
                    r="54"
                    fill="none"
                    stroke="var(--aqt-border)"
                    strokeWidth="18"
                  />
                  {stageDonut.segments.map((segment) => (
                    <circle
                      key={segment.name}
                      cx="70"
                      cy="70"
                      r="54"
                      fill="none"
                      stroke={segment.color}
                      strokeWidth="18"
                      strokeDasharray={segment.dashArray}
                      strokeDashoffset={segment.dashOffset}
                      transform="rotate(-90 70 70)"
                      strokeLinecap="butt"
                    />
                  ))}
                </svg>
                <div className={styles.donutCenter}>
                  <span className={styles.donutValue}>{countLabel(format, stageDonut.total)}</span>
                  <span className={styles.donutLabel}>{t("encounters.insights.series")}</span>
                </div>
              </div>
              <div className={styles.donutLegend}>
                {stageDonut.segments.length ? (
                  stageDonut.segments.map((segment) => (
                    <div key={segment.name} className={styles.legendRow}>
                      <span
                        aria-hidden
                        className={styles.legendSwatch}
                        style={{ background: segment.color }}
                      />
                      <span className={styles.legendName}>{segment.name}</span>
                      <span className={cn(styles.legendValue, "tabular-nums")}>
                        {countLabel(format, segment.count)} · {segment.pct}%
                      </span>
                    </div>
                  ))
                ) : (
                  <span className={styles.dim}>{t("encounters.insights.noStageData")}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function RowCells({
  row,
  cols,
  matrix,
  max
}: Readonly<{
  row: number;
  cols: number[];
  matrix: Record<string, number>;
  max: number;
}>) {
  const format = useFormatter();
  return (
    <>
      <div className={styles.scoreSide}>{row}</div>
      {cols.map((col) => {
        const count = matrix[`${row}-${col}`] ?? 0;
        const alpha = max > 0 ? Math.max(0.05, count / max) : 0;
        return (
          <div
            key={`${row}-${col}`}
            className={cn(
              styles.scoreCellHeat,
              count === 0 && styles.scoreCellEmpty,
              "tabular-nums"
            )}
            style={{ "--alpha": String(alpha) } as CSSProperties}
          >
            {count > 0 ? countLabel(format, count) : "—"}
          </div>
        );
      })}
    </>
  );
}

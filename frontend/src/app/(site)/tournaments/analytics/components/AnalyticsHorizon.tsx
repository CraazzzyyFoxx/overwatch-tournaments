"use client";

import { TeamAnalytics } from "@/types/analytics.types";
import { formatAnalyticsNumber } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { cn } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { useTranslation } from "@/i18n/LanguageContext";
import styles from "./AnalyticsRedesign.module.css";

interface AnalyticsHorizonProps {
  teams: TeamAnalytics[];
}

const AnalyticsHorizon = ({ teams }: AnalyticsHorizonProps) => {
  const { t } = useTranslation();
  const teamsWithPlacement = teams.filter((team) => team.placement != null);
  const positionValues = teamsWithPlacement.flatMap((team) => [
    team.placement ?? 1,
    team.predicted_place ?? team.placement ?? 1
  ]);
  const minPosition = Math.min(...positionValues);
  const maxPosition = Math.max(...positionValues);
  const scale = (position: number) => {
    const span = maxPosition - minPosition;
    if (!Number.isFinite(span) || span <= 0) return 50;
    return Math.max(0, Math.min(100, (position - minPosition) / span * 100));
  };
  const avgDelta = teamsWithPlacement.length
    ? teamsWithPlacement.reduce((sum, team) => sum + Math.abs(team.placement_delta ?? 0), 0) / teamsWithPlacement.length
    : 0;

  return (
    <Card className="overflow-hidden">
      <div className={styles.horizon}>
        <div>
          <div className={styles.sectionTitle}>{t("analytics.horizon.title")}</div>
          <div className={styles.sectionSub}>{t("analytics.horizon.subtitle")}</div>
        </div>
        <div className={styles.horizonGrid}>
          {teamsWithPlacement.map((team) => {
            const actual = team.placement ?? 1;
            const predicted = team.predicted_place ?? actual;
            const predictedPct = scale(predicted);
            const actualPct = scale(actual);
            const left = Math.min(predictedPct, actualPct);
            const width = Math.abs(predictedPct - actualPct);
            const divergent = Math.abs(team.placement_delta ?? 0) >= 4;

            return (
              <div
                key={team.id}
                className={cn(styles.horizonRow, divergent && styles.horizonDivergent)}
              >
                <span className={styles.horizonRank}>{actual}</span>
                <div className={styles.horizonTrack}>
                  <span className={styles.horizonTrackBg} />
                  <span
                    className={cn(styles.horizonLink, divergent && styles.horizonLinkDivergent)}
                    style={{ left: `${left}%`, width: `${width}%` }}
                  />
                  <span
                    className={cn(styles.horizonDot, styles.horizonPredicted)}
                    style={{ left: `${predictedPct}%` }}
                    title={t("analytics.horizon.predictedTip", { place: predicted })}
                  />
                  <span
                    className={cn(styles.horizonDot, styles.horizonActual)}
                    style={{ left: `${actualPct}%` }}
                    title={t("analytics.horizon.actualTip", { place: actual })}
                  />
                  <span
                    className={styles.horizonName}
                    style={{ left: `calc(${Math.max(predictedPct, actualPct)}% + 10px)` }}
                    title={team.name}
                  >
                    {team.name}
                  </span>
                </div>
                <span className={styles.horizonRank}>{predicted}</span>
              </div>
            );
          })}
        </div>
        <div className={styles.legend}>
          <span className={styles.legendSwatch}>
            <span className={cn(styles.swatch, styles.swatchOutline)} />
            {t("analytics.horizon.predicted")}
          </span>
          <span className={styles.legendSwatch}>
            <span className={cn(styles.swatch, styles.swatchActual)} />
            {t("analytics.horizon.actual")}
          </span>
          <span className="ml-auto">
            {t("analytics.horizon.deltaAvg")}{" "}
            <strong className="text-foreground">{formatAnalyticsNumber(avgDelta, 1)}</strong>
          </span>
        </div>
      </div>
    </Card>
  );
};

export default AnalyticsHorizon;

"use client";

import React, { useMemo } from "react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import DeltaPill from "@/app/(site)/tournaments/analytics/components/DeltaPill";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface PredictedActualHorizonProps {
  teams: TeamVM[];
  onExplain?: (term: GlossaryTerm) => void;
}

function moveColor(delta: number): string {
  if (delta === 0) return "var(--c-muted)";
  return delta > 0 ? "var(--c-up)" : "var(--c-down)";
}

/**
 * The bracket-wide predicted-vs-actual chart: one track per team, an open ring
 * at the predicted place connecting to the filled dot at the actual finish,
 * coloured by direction. Public (v1 placement / predicted_place only).
 */
export default function PredictedActualHorizon({ teams, onExplain }: PredictedActualHorizonProps) {
  const { t } = useTranslation();

  const rows = useMemo(
    () =>
      teams
        .filter((team) => team.placement != null && team.predicted_place != null)
        .sort((a, b) => (a.placement as number) - (b.placement as number)),
    [teams],
  );

  if (rows.length < 2) return null;
  const count = rows.length;
  const pos = (place: number) => ((place - 1) / (count - 1)) * 100;

  return (
    <div className={styles.cCard}>
      <div className={styles.cHzHead}>
        <span className={styles.cCardTitle}>
          {t("analytics.community.horizon.title")}{" "}
          <InfoDot term="predicted_move" onExplain={onExplain} />
        </span>
        <span className={styles.cHzCount}>
          {t("analytics.community.horizon.allTeams", { count })}
        </span>
      </div>

      <div className={styles.cHzAxis}>
        <span />
        <span />
        <span className={styles.cHzScale}>
          <span>{t("analytics.community.horizon.scaleStart")}</span>
          <span>{t("analytics.community.horizon.scaleFinish")}</span>
          <span>{t("analytics.community.horizon.scaleEnd", { count })}</span>
        </span>
        <span />
      </div>

      <div className={styles.cHzRows}>
        {rows.map((team) => {
          const predicted = team.predicted_place as number;
          const actual = team.placement as number;
          const delta = team.placement_delta ?? 0;
          const predictedPct = pos(predicted);
          const actualPct = pos(actual);
          const low = Math.min(predictedPct, actualPct);
          const high = Math.max(predictedPct, actualPct);
          const color = moveColor(delta);

          return (
            <div className={styles.cHzRow} key={team.id}>
              <span className={styles.cHzRank}>{actual}</span>
              <span className={styles.cHzName} title={team.name}>
                {team.name}
              </span>
              <span className={styles.cHorizonTrack}>
                <span className={styles.cHorizonLine} />
                {delta !== 0 ? (
                  <span
                    className={styles.cHconn}
                    style={{ left: `${low}%`, width: `${high - low}%`, background: color }}
                  />
                ) : null}
                <span
                  className={cn(styles.cHdot, styles.cHdotPred)}
                  style={{ left: `${predictedPct}%` }}
                />
                <span
                  className={styles.cHdot}
                  style={{ left: `${actualPct}%`, background: color, border: `2px solid ${color}` }}
                />
              </span>
              <span className={styles.cHzDelta}>
                <DeltaPill delta={team.placement_delta} />
              </span>
            </div>
          );
        })}
      </div>

      <div className={styles.cHzLegend}>
        <span className={styles.cLg}>
          <span className={cn(styles.cLgDot, styles.cHdotPred)} />
          {t("analytics.community.horizon.predicted")}
        </span>
        <span className={styles.cLg}>
          <span className={styles.cLgDot} style={{ background: "var(--c-up)" }} />
          {t("analytics.community.horizon.climbed")}
        </span>
        <span className={styles.cLg}>
          <span className={styles.cLgDot} style={{ background: "var(--c-down)" }} />
          {t("analytics.community.horizon.fellShort")}
        </span>
      </div>
    </div>
  );
}

"use client";

import React, { useState } from "react";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { usePermissions } from "@/hooks/usePermissions";
import type { DivisionGridVersion } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { roleKey } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { PlayerVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { GlossaryTerm, isAnomalyGlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import ImpactBar from "@/app/(site)/tournaments/analytics/components/community/ImpactBar";
import ChangeShiftDialog from "@/app/(site)/tournaments/analytics/components/community/ChangeShiftDialog";
import ExplanationPopover from "@/app/(site)/tournaments/analytics/components/ExplanationPopover";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface PlayerDetailProps {
  player: PlayerVM;
  teamName: string;
  tournamentGrid?: DivisionGridVersion | null;
  canReadV2?: boolean;
  onExplain?: (term: GlossaryTerm) => void;
}

function impactColor(value: number): string {
  if (value >= 66) return "var(--c-up)";
  if (value <= 34) return "var(--c-down)";
  return "var(--c-info)";
}

export default function PlayerDetail({
  player,
  teamName,
  tournamentGrid,
  canReadV2 = false,
  onExplain,
}: PlayerDetailProps) {
  const { t } = useTranslation();
  const { hasPermission } = usePermissions();
  const [editing, setEditing] = useState(false);
  const canEdit = hasPermission("analytics.update");

  const direction = player.predicted_direction;
  const up = direction === "promote";
  const down = direction === "demote";
  const moveColor = up ? "var(--c-up)" : down ? "var(--c-down)" : "var(--c-muted)";
  const moveWord = up
    ? t("analytics.community.player.climb")
    : down
      ? t("analytics.community.player.drop")
      : t("analytics.community.player.hold");

  const rk = roleKey(player.role);
  const roleLabel = rk ? t(`analytics.community.role.${rk}`) : player.role;
  const roleLower = roleLabel.toLowerCase();
  const confPct = Math.round(player.confidence * 100);
  const predictedDivision = player.predicted_division ?? player.division;
  const isNew = player.is_newcomer || player.is_newcomer_role;

  const impactDesc =
    player.impact >= 80
      ? t("analytics.community.player.impactElite")
      : player.impact >= 50
        ? t("analytics.community.player.impactAbove")
        : player.impact >= 34
          ? t("analytics.community.player.impactMid")
          : t("analytics.community.player.impactBelow");
  const confDesc =
    player.confidence >= 0.8
      ? t("analytics.community.player.confidencePlenty")
      : player.confidence >= 0.6
        ? t("analytics.community.player.confidenceSolid")
        : t("analytics.community.player.confidenceThin");

  const flag = player.anomalies[0];
  const why: string[] = [];
  if (flag) {
    why.push(t("analytics.community.why.flag", { kind: flag.kind }));
    why.push(t("analytics.community.why.flagSignal", { pct: Math.round(flag.score * 100) }));
  } else if (up) {
    why.push(t("analytics.community.why.climbImpact", { division: player.division, role: roleLower }));
    why.push(t("analytics.community.why.climbConfidence", { pct: confPct }));
  } else if (down) {
    why.push(t("analytics.community.why.dropImpact", { division: player.division, role: roleLower }));
    why.push(t("analytics.community.why.dropConsistent", { maps: player.sample_matches }));
  } else {
    why.push(t("analytics.community.why.holdInBand", { division: player.division }));
    why.push(
      player.confidence < 0.6
        ? t("analytics.community.why.holdThin", { pct: confPct })
        : t("analytics.community.why.holdSteady"),
    );
  }

  return (
    <>
      {/* hero */}
      <div className={cn(styles.cCard, styles.cPlayerHero)}>
        <DivisionIcon division={player.division} tournamentGrid={tournamentGrid} width={54} height={54} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className={styles.cPlayerName}>
            {player.name}
            {isNew ? (
              <span className={styles.cTagNew}>
                {player.is_newcomer_role
                  ? t("analytics.community.player.newRoleTag")
                  : t("analytics.community.player.newTag")}
              </span>
            ) : null}
          </div>
          <div className={styles.cPlayerRole}>
            <PlayerRoleIcon role={player.role} size={15} />
            <span>
              {t("analytics.community.player.roleLine", {
                role: roleLabel,
                division: player.division,
                team: teamName,
              })}
            </span>
          </div>
        </div>
      </div>

      {/* predicted move */}
      <div
        className={cn(styles.cCard, up && styles.cMoveCardUp, down && styles.cMoveCardDown)}
      >
        <span className={styles.cCardTitle}>
          {t("analytics.community.player.predictedMove")}{" "}
          <InfoDot term="predicted_move" onExplain={onExplain} />
        </span>
        <div className={styles.cBetween} style={{ marginTop: 4 }}>
          <div>
            <div className={styles.cMoveWord} style={{ color: moveColor }}>
              {moveWord}
            </div>
            {direction !== "flat" ? (
              <div className={styles.cMoveSub}>
                {t("analytics.community.player.divMove", {
                  from: player.division,
                  to: predictedDivision,
                })}
              </div>
            ) : null}
          </div>
          {direction !== "flat" ? (
            <div className={styles.cMoveBadges}>
              <DivisionIcon division={player.division} tournamentGrid={tournamentGrid} width={38} height={38} />
              <ArrowRight size={18} style={{ color: moveColor }} aria-hidden="true" />
              <DivisionIcon division={predictedDivision} tournamentGrid={tournamentGrid} width={44} height={44} />
            </div>
          ) : null}
        </div>
      </div>

      {/* metrics */}
      <div className={styles.cMetricGrid}>
        <div className={styles.cMetric}>
          <span className={styles.cMetricL}>
            {t("analytics.community.player.impact")}{" "}
            <InfoDot term="impact" onExplain={onExplain} />
          </span>
          <span className={styles.cMetricV} style={{ color: impactColor(player.impact) }}>
            {player.impact}
          </span>
          <span className={styles.cMetricS}>{impactDesc}</span>
        </div>
        <div className={styles.cMetric}>
          <span className={styles.cMetricL}>
            {t("analytics.community.player.confidence")}{" "}
            <InfoDot term="confidence" onExplain={onExplain} />
          </span>
          <span className={cn(styles.cMetricV, styles.cTnum)}>{confPct}%</span>
          <span className={styles.cMetricS}>{confDesc}</span>
        </div>
      </div>

      {/* impact percentile */}
      <div className={styles.cCard} style={{ padding: "13px 16px" }}>
        <div className={styles.cBetween}>
          <span className={styles.cCardTitle}>
            {t("analytics.community.player.percentileTitle")}
          </span>
          <span className={styles.cMetricS}>
            {t("analytics.community.player.percentileVs", {
              division: player.division,
              role: roleLower,
            })}
          </span>
        </div>
        <div style={{ marginTop: 10 }}>
          <ImpactBar value={player.impact} />
        </div>
      </div>

      {/* flag card */}
      {flag ? (
        <div className={styles.cFlagCard}>
          <div className={styles.cFlagCardHead}>
            <span className={styles.cFlagDot} />
            <span className={styles.cCardTitle} style={{ color: "var(--c-warn)" }}>
              {t("analytics.community.player.flagTitle", { kind: flag.kind })}{" "}
              {isAnomalyGlossaryTerm(flag.kind) ? (
                <InfoDot term={flag.kind} onExplain={onExplain} />
              ) : null}
            </span>
          </div>
          <p className={styles.cFlagCardBody}>
            {t("analytics.community.player.flagBody", { kind: flag.kind })}
          </p>
        </div>
      ) : null}

      {/* why */}
      <div className={styles.cCard}>
        <div className={styles.cBetween}>
          <span className={styles.cCardTitle}>{t("analytics.community.player.whyTitle")}</span>
          {canReadV2 ? (
            <ExplanationPopover playerId={player.id} tournamentId={player.tournament_id} />
          ) : null}
        </div>
        <ul className={styles.cWhy}>
          {why.map((line, index) => (
            <li key={index}>
              <span className={styles.cWhyBullet} style={{ background: moveColor }} />
              {line}
            </li>
          ))}
        </ul>
      </div>

      {/* organizer-only manual shift */}
      {canEdit ? (
        <div className={styles.cShiftEdit}>
          <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
            {t("analytics.standings.editManualShift")}
          </Button>
          <ChangeShiftDialog player={player} open={editing} onOpenChange={setEditing} />
        </div>
      ) : null}
    </>
  );
}

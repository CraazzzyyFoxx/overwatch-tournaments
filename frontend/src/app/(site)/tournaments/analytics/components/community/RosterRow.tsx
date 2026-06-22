"use client";

import React from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import type { DivisionGridVersion } from "@/types/workspace.types";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { PlayerVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import AnomalyTooltip from "@/app/(site)/tournaments/analytics/components/AnomalyTooltip";
import ImpactBar from "@/app/(site)/tournaments/analytics/components/community/ImpactBar";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface RosterRowProps {
  player: PlayerVM;
  tournamentGrid?: DivisionGridVersion | null;
  onSelect: () => void;
}

function MoveChip({ player }: { player: PlayerVM }) {
  const { t } = useTranslation();
  const target = player.predicted_division ?? player.division;

  if (player.predicted_direction === "promote") {
    return (
      <span className={cn(styles.cMove, styles.cMoveUp)}>
        <ArrowUp aria-hidden="true" />
        {t("analytics.community.move.climb", { division: target })}
      </span>
    );
  }
  if (player.predicted_direction === "demote") {
    return (
      <span className={cn(styles.cMove, styles.cMoveDown)}>
        <ArrowDown aria-hidden="true" />
        {t("analytics.community.move.drop", { division: target })}
      </span>
    );
  }
  return (
    <span className={cn(styles.cMove, styles.cMoveFlat)}>
      <Minus aria-hidden="true" />
      {t("analytics.community.move.hold")}
    </span>
  );
}

/**
 * A roster line in the team detail: role + division badge, name (with newcomer
 * tag), impact bar, optional watch-flag chip, and the predicted move. Selecting
 * it opens the player detail.
 */
export default function RosterRow({ player, tournamentGrid, onSelect }: RosterRowProps) {
  const { t } = useTranslation();
  const isNew = player.is_newcomer || player.is_newcomer_role;
  const flag = player.anomalies[0];

  return (
    <div
      className={styles.cRosterRow}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <span className={styles.cRoleChip}>
        <PlayerRoleIcon role={player.role} size={15} />
      </span>
      <span className={styles.cBadgeWrap}>
        <DivisionIcon division={player.division} tournamentGrid={tournamentGrid} width={30} height={30} />
      </span>
      <span className={styles.cPId}>
        <span className={styles.cPName}>
          {player.name}
          {isNew ? (
            <span className={styles.cTagNew}>
              {player.is_newcomer_role
                ? t("analytics.community.player.newRoleTag")
                : t("analytics.community.player.newTag")}
            </span>
          ) : null}
        </span>
        <span className={styles.cPMeta}>
          <span style={{ width: 84 }}>
            <ImpactBar value={player.impact} />
          </span>
          {flag ? (
            <AnomalyTooltip kind={flag.kind} reasons={flag.reasons} focusable={false}>
              <span className={styles.cFlag}>
                <span className={styles.cFlagDot} />
                {flag.kind}
              </span>
            </AnomalyTooltip>
          ) : null}
        </span>
      </span>
      <MoveChip player={player} />
    </div>
  );
}

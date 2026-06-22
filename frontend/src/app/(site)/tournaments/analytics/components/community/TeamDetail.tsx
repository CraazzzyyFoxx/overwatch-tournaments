"use client";

import React, { useMemo } from "react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { sortTeamPlayers } from "@/utils/player";
import { formatPlace } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import DeltaPill from "@/app/(site)/tournaments/analytics/components/DeltaPill";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import RosterRow from "@/app/(site)/tournaments/analytics/components/community/RosterRow";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface TeamDetailProps {
  team: TeamVM;
  totalTeams: number;
  onSelectPlayer: (playerId: number) => void;
  onExplain?: (term: GlossaryTerm) => void;
}

function moveColor(delta: number | null): string {
  if (delta == null || delta === 0) return "var(--c-muted)";
  return delta > 0 ? "var(--c-up)" : "var(--c-down)";
}

/** The single-row predicted → actual horizon for one team. */
function TeamHorizon({ team, totalTeams }: { team: TeamVM; totalTeams: number }) {
  const { t, locale } = useTranslation();
  const predicted = team.predicted_place;
  const actual = team.placement;
  if (predicted == null || actual == null || totalTeams < 2) return null;

  const pos = (place: number) => ((place - 1) / (totalTeams - 1)) * 100;
  const predictedPct = pos(predicted);
  const actualPct = pos(actual);
  const low = Math.min(predictedPct, actualPct);
  const high = Math.max(predictedPct, actualPct);
  const color = moveColor(team.placement_delta);

  return (
    <>
      <div className={styles.cHorizonRow}>
        <span className={styles.cHorizonEnd}>{t("analytics.community.horizon.scaleStart")}</span>
        <span className={styles.cHorizonTrack}>
          <span className={styles.cHorizonLine} />
          {team.placement_delta != null && team.placement_delta !== 0 ? (
            <span
              className={styles.cHconn}
              style={{ left: `${low}%`, width: `${high - low}%`, background: color }}
            />
          ) : null}
          <span className={cn(styles.cHdot, styles.cHdotPred)} style={{ left: `${predictedPct}%` }} />
          <span
            className={styles.cHdot}
            style={{ left: `${actualPct}%`, background: color, border: `2px solid ${color}` }}
          />
        </span>
        <span className={styles.cHorizonEnd} style={{ textAlign: "right" }}>
          {t("analytics.community.horizon.scaleEnd", { count: totalTeams })}
        </span>
      </div>
      <div className={styles.cHorizonLegend}>
        <span>
          <span className={cn(styles.cHdotPred, styles.cHdotStatic)} style={{ borderRadius: "50%" }} />
          {t("analytics.community.team.predictedShort", { place: formatPlace(predicted, locale) })}
        </span>
        <span>
          <span
            className={styles.cHdotStatic}
            style={{ background: color, borderRadius: "50%" }}
          />
          {t("analytics.community.team.finishedShort", { place: formatPlace(actual, locale) })}
        </span>
      </div>
    </>
  );
}

/**
 * Team drill-down: place + delta header, the predicted-vs-actual horizon, and
 * the roster (each player opens the player detail).
 */
export default function TeamDetail({ team, totalTeams, onSelectPlayer, onExplain }: TeamDetailProps) {
  const { t, locale } = useTranslation();
  const tournamentGrid = team.tournament?.division_grid_version;
  const players = useMemo(() => sortTeamPlayers(team.players), [team.players]);
  const groupName = team.group?.name ?? "—";

  return (
    <>
      <div className={styles.cCard}>
        <div className={styles.cTeamHeadTop}>
          <div>
            <div className={styles.cTeamEyebrow}>
              {t("analytics.community.team.groupRecord", {
                group: groupName,
                wins: team.wins,
                losses: team.losses,
              })}
            </div>
            <div className={styles.cTeamPlaceRow}>
              <span className={cn(styles.cTeamPlace, team.placement === 1 && styles.cTeamPlaceWin)}>
                {formatPlace(team.placement, locale)}
              </span>
              <span className={styles.cTeamNameBig}>{team.name}</span>
            </div>
          </div>
          <DeltaPill delta={team.placement_delta} />
        </div>

        <div style={{ marginTop: 16 }}>
          <span className={styles.cCardTitle}>
            {t("analytics.community.team.predictedVsActual")}{" "}
            <InfoDot term="predicted_move" onExplain={onExplain} />
          </span>
          <TeamHorizon team={team} totalTeams={totalTeams} />
        </div>
      </div>

      <div className={styles.cRosterTitle}>
        {t("analytics.community.team.rosterCount", { count: players.length })}
      </div>
      <div className={styles.cRoster}>
        {players.map((player) => (
          <RosterRow
            key={player.id}
            player={player}
            tournamentGrid={tournamentGrid}
            onSelect={() => onSelectPlayer(player.id)}
          />
        ))}
      </div>
    </>
  );
}

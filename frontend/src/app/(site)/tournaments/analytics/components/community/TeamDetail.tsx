"use client";

import React, { useMemo } from "react";
import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslations, useLocale } from "next-intl";
import { sortTeamPlayers } from "@/utils/player";
import { StandingsDistribution } from "@/types/analytics.types";
import { formatPlace } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { GlossaryTerm } from "@/app/(site)/tournaments/analytics/analytics-glossary";
import DeltaPill from "@/app/(site)/tournaments/analytics/components/DeltaPill";
import InfoDot from "@/app/(site)/tournaments/analytics/components/InfoDot";
import RosterRow from "@/app/(site)/tournaments/analytics/components/community/RosterRow";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

interface TeamDetailProps {
  team: TeamVM;
  /** Monte-Carlo distribution for this team (organizer-only; woven into detail). */
  distribution?: StandingsDistribution;
  onSelectPlayer: (playerId: number) => void;
  onExplain?: (term: GlossaryTerm) => void;
}

function moveColor(delta: number | null): string {
  if (delta == null || delta === 0) return "var(--c-muted)";
  return delta > 0 ? "var(--c-up)" : "var(--c-down)";
}

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Compact Monte-Carlo block — woven into the team detail for organizers. */
function MonteCarlo({ distribution }: { distribution: StandingsDistribution }) {
  const t = useTranslations();
  const bars = useMemo(() => {
    const entries = Object.entries(distribution.position_histogram)
      .map(([pos, count]) => ({ pos: Number(pos), count }))
      .sort((a, b) => a.pos - b.pos);
    const max = entries.reduce((m, e) => Math.max(m, e.count), 0) || 1;
    return entries.map((e) => ({ ...e, height: Math.max(6, (e.count / max) * 100) }));
  }, [distribution.position_histogram]);

  return (
    <div className={styles.cMonte}>
      <span className={styles.cCardTitle}>{t("analytics.distribution.title")}</span>
      <div className={styles.cMonteProbs}>
        <div className={styles.cMonteProb}>
          <div className={styles.cMonteProbL}>{t("analytics.distribution.top1")}</div>
          <div className={styles.cMonteProbV}>{percent(distribution.prob_top1)}</div>
        </div>
        <div className={styles.cMonteProb}>
          <div className={styles.cMonteProbL}>{t("analytics.distribution.top3")}</div>
          <div className={styles.cMonteProbV}>{percent(distribution.prob_top3)}</div>
        </div>
        <div className={styles.cMonteProb}>
          <div className={styles.cMonteProbL}>{t("analytics.distribution.top8")}</div>
          <div className={styles.cMonteProbV}>{percent(distribution.prob_top8)}</div>
        </div>
      </div>
      <div className={styles.cMonteHist} aria-hidden="true">
        {bars.map((bar) => (
          <span
            key={bar.pos}
            className={styles.cMonteBar}
            style={{ height: `${bar.height}%` }}
            title={`#${bar.pos}: ${bar.count}`}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Team drill-down: place + delta header, a compact predicted→actual summary
 * (the full connector lives inline in the standings row), the organizer
 * Monte-Carlo distribution, and the roster (each player opens player detail).
 */
export default function TeamDetail({
  team,
  distribution,
  onSelectPlayer,
  onExplain,
}: TeamDetailProps) {
  const t = useTranslations();
  const locale = useLocale();
  const tournamentGrid = team.tournament?.division_grid_version;
  const players = useMemo(() => sortTeamPlayers(team.players), [team.players]);
  const groupName = team.group?.name ?? "—";
  const hasForecast = team.predicted_place != null && team.placement != null;
  const color = moveColor(team.placement_delta);

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

        {hasForecast ? (
          <div className={styles.cPvaLine}>
            <span className={cn(styles.cPvaDot, styles.cHdotPred)} />
            {t("analytics.community.team.predictedShort", {
              place: formatPlace(team.predicted_place, locale),
            })}
            <ArrowRight size={13} aria-hidden="true" />
            <span className={styles.cPvaDot} style={{ background: color }} />
            {t("analytics.community.team.finishedShort", {
              place: formatPlace(team.placement, locale),
            })}
            <InfoDot term="predicted_move" onExplain={onExplain} />
          </div>
        ) : null}

        {distribution ? <MonteCarlo distribution={distribution} /> : null}
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

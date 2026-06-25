"use client";

import React, { useMemo } from "react";
import { ChevronRight } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { TeamVM } from "@/app/(site)/tournaments/analytics/useAnalyticsViewModel";
import { formatPlace } from "@/app/(site)/tournaments/analytics/analytics.helpers";
import DeltaPill from "@/app/(site)/tournaments/analytics/components/DeltaPill";
import styles from "@/app/(site)/tournaments/analytics/components/AnalyticsRedesign.module.css";

export type StandingsMode = "standings" | "movers" | "watch";

interface StandingsListProps {
  teams: TeamVM[];
  selectedTeamId: number | null;
  onSelectTeam: (teamId: number) => void;
  mode: StandingsMode;
  onModeChange: (mode: StandingsMode) => void;
  /** Trailing control on the sort-tab row (the list/table view toggle). */
  headerEnd?: React.ReactNode;
}

const MODES: StandingsMode[] = ["standings", "movers", "watch"];

function placementRank(placement: number | null): number {
  return placement == null ? Number.MAX_SAFE_INTEGER : placement;
}

function sortTeams(teams: TeamVM[], mode: StandingsMode): TeamVM[] {
  if (mode === "movers") {
    return [...teams].sort(
      (a, b) => Math.abs(b.placement_delta ?? 0) - Math.abs(a.placement_delta ?? 0),
    );
  }
  if (mode === "watch") {
    return teams.filter((team) => team.flagCount > 0);
  }
  return [...teams].sort((a, b) => placementRank(a.placement) - placementRank(b.placement));
}

function moveColor(delta: number | null): string {
  if (delta == null || delta === 0) return "var(--c-muted)";
  return delta > 0 ? "var(--c-up)" : "var(--c-down)";
}

/** The per-row predicted → actual mini-connector — the horizon, inlined. */
function RowHorizon({ team, maxPosition }: { team: TeamVM; maxPosition: number }) {
  const { t, locale } = useTranslation();
  const predicted = team.predicted_place;
  const actual = team.placement;
  if (predicted == null || actual == null || maxPosition < 2) {
    return <span className={styles.cRowHz} aria-hidden="true" />;
  }
  const pos = (place: number) => ((place - 1) / (maxPosition - 1)) * 100;
  const predictedPct = pos(predicted);
  const actualPct = pos(actual);
  const low = Math.min(predictedPct, actualPct);
  const high = Math.max(predictedPct, actualPct);
  const color = moveColor(team.placement_delta);

  return (
    <span className={styles.cRowHz}>
      <span className={styles.cRowHzPred}>
        {t("analytics.community.standings.predShort", { place: formatPlace(predicted, locale) })}
      </span>
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
    </span>
  );
}

/**
 * The community standings: a sortable list (Standings / Biggest movers / Watch
 * list) where each row carries its predicted→actual connector inline and
 * selects a team for the detail panel. The single team spine of the page.
 */
export default function StandingsList({
  teams,
  selectedTeamId,
  onSelectTeam,
  mode,
  onModeChange,
  headerEnd,
}: StandingsListProps) {
  const { t } = useTranslation();
  const rows = useMemo(() => sortTeams(teams, mode), [teams, mode]);
  const maxPosition = useMemo(
    () => teams.reduce((max, team) => Math.max(max, team.placement ?? 0), 0),
    [teams],
  );

  const modeLabel: Record<StandingsMode, string> = {
    standings: t("analytics.community.standings.sortStandings"),
    movers: t("analytics.community.standings.sortMovers"),
    watch: t("analytics.community.standings.sortWatch"),
  };

  return (
    <div className={styles.cStandings}>
      <div className={styles.cStandingsHead}>
        <div className={styles.cSeg} role="tablist">
          {MODES.map((value) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              data-on={mode === value}
              className={styles.cSegBtn}
              onClick={() => onModeChange(value)}
            >
              {modeLabel[value]}
            </button>
          ))}
        </div>
        {headerEnd}
      </div>

      <div className={styles.cTeamRows}>
        {rows.length === 0 ? (
          <div className={styles.cStandingsEmpty}>
            {t("analytics.community.standings.watchEmpty")}
          </div>
        ) : (
          rows.map((team) => {
            const groupName = team.group?.name ?? "—";
            return (
              <button
                key={team.id}
                type="button"
                className={styles.cTeamRow}
                data-sel={selectedTeamId === team.id}
                onClick={() => onSelectTeam(team.id)}
              >
                <span className={cn(styles.cRank, team.placement === 1 && styles.cRank1)}>
                  {team.placement ?? "—"}
                </span>
                <span className={styles.cTeamId}>
                  <span className={styles.cTeamName}>{team.name}</span>
                  <span className={styles.cTeamMeta}>
                    <span>
                      {team.wins}–{team.losses}
                    </span>
                    <span>·</span>
                    <span>{t("analytics.community.standings.group", { group: groupName })}</span>
                    {team.flagCount > 0 ? (
                      <>
                        <span>·</span>
                        <span className={styles.cFlagText}>
                          {t(
                            team.flagCount === 1
                              ? "analytics.community.standings.flagCountOne"
                              : "analytics.community.standings.flagCount",
                            { count: team.flagCount },
                          )}
                        </span>
                      </>
                    ) : null}
                  </span>
                </span>
                <RowHorizon team={team} maxPosition={maxPosition} />
                <DeltaPill delta={team.placement_delta} />
                <ChevronRight className={styles.cChevron} size={16} aria-hidden="true" />
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
